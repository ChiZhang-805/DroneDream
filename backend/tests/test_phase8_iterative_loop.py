"""Phase 8 tests for the iterative GPT tuning loop and acceptance evaluator."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select


class FakeOpenAIClient:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        self.calls += 1
        if not self._responses:
            raise RuntimeError("FakeOpenAIClient ran out of canned responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture()
def gpt_ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    db_path = tmp_path / "gpt.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-key")
    from app import config as config_module

    config_module.get_settings.cache_clear()

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    import app.db as db_module  # type: ignore[import-not-found]
    import app.models as models_module  # type: ignore[import-not-found]
    import app.orchestration.acceptance as acceptance  # type: ignore[import-not-found]
    import app.orchestration.aggregation as aggregation  # type: ignore[import-not-found]
    import app.orchestration.job_manager as job_manager  # type: ignore[import-not-found]
    import app.orchestration.runner as runner  # type: ignore[import-not-found]
    import app.orchestration.trial_executor as trial_executor  # type: ignore[import-not-found]
    import app.services.jobs as jobs_service  # type: ignore[import-not-found]  # noqa: I001

    db_module.init_db()

    yield {
        "db_module": db_module,
        "models": models_module,
        "schemas": __import__("app.schemas", fromlist=["*"]),
        "jobs_service": jobs_service,
        "acceptance": acceptance,
        "aggregation": aggregation,
        "job_manager": job_manager,
        "runner": runner,
        "trial_executor": trial_executor,
    }

    config_module.get_settings.cache_clear()


def _create_job(
    ctx: dict[str, object],
    *,
    strategy: str = "gpt",
    target_rmse: float | None = 0.5,
    max_iterations: int = 3,
    min_pass_rate: float = 0.5,
) -> str:
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]
    req = schemas.JobCreateRequest(
        simulator_backend="mock",
        optimizer_strategy=strategy,
        max_iterations=max_iterations,
        trials_per_candidate=2,
        acceptance_criteria=schemas.AcceptanceCriteria(
            target_rmse=target_rmse, min_pass_rate=min_pass_rate
        ),
        openai=(
            schemas.OpenAIConfig(api_key="sk-iterative-test")
            if strategy in {"gpt", "llm_harness"}
            else None
        ),
    )
    with db_module.SessionLocal() as db:
        job = jobs_service.create_job(db, req)
        return job.id


def _drive(ctx: dict[str, object], job_id: str, *, client: object | None, max_ticks: int = 60):
    models_mod = ctx["models"]
    runner = ctx["runner"]
    aggregation = ctx["aggregation"]
    db_module = ctx["db_module"]

    aggregation.set_llm_client_override(client)
    try:
        for _ in range(max_ticks):
            runner.tick("iter-worker")
            with db_module.SessionLocal() as db:
                job = db.get(models_mod.Job, job_id)
                if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                    return job.status
    finally:
        aggregation.set_llm_client_override(None)
    return None


def _gpt_proposal(kp: float) -> dict[str, Any]:
    return {
        "proposals": [
            {
                "label": f"kp_{kp}",
                "rationale": "Adjust kp_xy to reduce rmse",
                "parameters": {
                    "kp_xy": kp,
                    "kd_xy": 0.3,
                    "ki_xy": 0.08,
                    "vel_limit": 5.0,
                    "accel_limit": 4.0,
                    "disturbance_rejection": 0.6,
                },
            }
        ]
    }


def test_gpt_loop_dispatches_generation_after_baseline(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="gpt", target_rmse=0.01, max_iterations=2)
    client = FakeOpenAIClient(
        [_gpt_proposal(1.5), _gpt_proposal(0.9), RuntimeError("not needed")]
    )
    status = _drive(ctx, job_id, client=client, max_ticks=80)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.current_generation >= 1
        llm_candidates = [c for c in job.candidates if c.source_type == "llm_optimizer"]
        assert len(llm_candidates) >= 1
        assert all(c.trial_count == job.trials_per_candidate for c in llm_candidates)
        assert all("_rationale" not in c.parameter_json for c in llm_candidates)
        assert all(
            all(isinstance(value, int | float) for value in c.parameter_json.values())
            for c in llm_candidates
        )
        event_types = [e.event_type for e in job.events]
        assert "llm_proposal_started" in event_types
        assert "generation_dispatched" in event_types
        assert "candidate_generated_from_llm" in event_types


def test_llm_harness_selects_and_executes_registered_tool_after_baseline(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(
        ctx,
        strategy="llm_harness",
        target_rmse=0.01,
        max_iterations=1,
    )
    client = FakeOpenAIClient(
        [
            {
                "decision": {
                    "tool_id": "cma_es",
                    "rationale": "Use bounded evolutionary search after the baseline.",
                }
            }
        ]
    )
    status = _drive(ctx, job_id, client=client, max_ticks=80)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimizer_strategy == "llm_harness"
        assert job.current_generation == 1
        assert any(
            candidate.source_type == "optimizer"
            for candidate in job.candidates
        )
        event_types = [event.event_type for event in job.events]
        assert "harness_decision_started" in event_types
        assert "harness_decision_accepted" in event_types
        assert "harness_tool_execution_result" in event_types
        assert "generation_dispatched" in event_types


def test_gpt_max_iterations_reached_yields_best_so_far(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="gpt", target_rmse=0.001, max_iterations=1)
    client = FakeOpenAIClient([_gpt_proposal(1.5), _gpt_proposal(1.8)])
    status = _drive(ctx, job_id, client=client, max_ticks=60)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimization_outcome == "max_iterations_reached"
        assert job.latest_error_code is None
        assert job.best_candidate_id is not None
        assert job.report is not None


def test_gpt_failure_marks_job_failed_with_llm_failed_outcome(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="gpt", target_rmse=0.001, max_iterations=3)
    client = FakeOpenAIClient([RuntimeError("openai is down")])
    status = _drive(ctx, job_id, client=client, max_ticks=60)
    assert status == "FAILED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimization_outcome == "llm_failed"
        assert job.latest_error_code == "LLM_FAILED"
        event_types = [e.event_type for e in job.events]
        assert "llm_proposal_failed" in event_types


def test_cancelling_during_llm_call_rolls_back_new_generation(gpt_ctx) -> None:
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="gpt", target_rmse=0.001, max_iterations=2)

    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db, "blocking-llm-worker"
            )
        if trial_id is None:
            break

    entered = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release the blocked LLM call")
            return _gpt_proposal(1.5)

    errors: list[BaseException] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    ctx["aggregation"].set_llm_client_override(BlockingClient())
    worker = threading.Thread(target=finalize_in_thread, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=10), "finalizer never reached the LLM call"
        with ctx["db_module"].SessionLocal() as db:
            ctx["jobs_service"].cancel_job(db, job_id)
        release.set()
        worker.join(timeout=10)
        assert not worker.is_alive(), "finalizer did not stop after cancellation"
    finally:
        release.set()
        ctx["aggregation"].set_llm_client_override(None)
        worker.join(timeout=10)

    assert errors == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "CANCELLED"
        assert job.current_generation == 0
        assert [candidate.source_type for candidate in job.candidates] == ["baseline"]
        assert job.report is None
        event_types = [event.event_type for event in job.events]
        assert "job_cancelled" in event_types
        assert "generation_dispatched" not in event_types
        assert "llm_proposal_completed" not in event_types


def test_llm_harness_concurrent_finalizers_dispatch_one_generation(gpt_ctx) -> None:
    """Two processes racing the first claim still produce one dispatch."""

    ctx = gpt_ctx
    job_id = _create_job(
        ctx,
        strategy="llm_harness",
        target_rmse=0.001,
        max_iterations=2,
    )
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "concurrent-finalizer-worker",
            )
        if trial_id is None:
            break

    entered = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.calls = 0

        def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
            with self._lock:
                self.calls += 1
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release provider call")
            return {
                "decision": {
                    "tool_id": "cma_es",
                    "rationale": "Use bounded evolutionary search.",
                }
            }

    client = BlockingClient()
    errors: list[BaseException] = []
    start_barrier = threading.Barrier(3)

    def finalize_in_thread() -> None:
        try:
            start_barrier.wait(timeout=10)
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db, limit=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    ctx["aggregation"].set_llm_client_override(client)
    workers = [
        threading.Thread(target=finalize_in_thread, daemon=True)
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        start_barrier.wait(timeout=10)
        assert entered.wait(timeout=10), "winning finalizer never reached provider"
        time.sleep(0.1)
        assert client.calls == 1
        release.set()
        for worker in workers:
            worker.join(timeout=10)
            assert not worker.is_alive(), "concurrent finalizer did not finish"
    finally:
        release.set()
        ctx["aggregation"].set_llm_client_override(None)
        for worker in workers:
            worker.join(timeout=10)

    assert errors == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "RUNNING"
        assert job.current_generation == 1
        assert job.finalization_claim_token is None
        event_types = [event.event_type for event in job.events]
        assert event_types.count("generation_dispatched") == 1
        assert event_types.count("harness_decision_accepted") == 1
        assert event_types.count("harness_tool_execution_result") == 1


def test_llm_harness_expired_claim_cannot_duplicate_generation(
    gpt_ctx,
    monkeypatch,
) -> None:
    """A reclaimed provider response must roll back without dispatching."""

    ctx = gpt_ctx
    job_id = _create_job(
        ctx,
        strategy="llm_harness",
        target_rmse=0.001,
        max_iterations=2,
    )
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "expired-claim-worker",
            )
        if trial_id is None:
            break

    first_call_entered = threading.Event()
    release_first_call = threading.Event()

    class RacingClient:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.calls = 0

        def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
            with self._lock:
                self.calls += 1
                call_number = self.calls
            if call_number == 1:
                first_call_entered.set()
                if not release_first_call.wait(timeout=10):
                    raise TimeoutError("test did not release stale provider call")
            return {
                "decision": {
                    "tool_id": "cma_es",
                    "rationale": "Use bounded evolutionary search.",
                }
            }

    class DisabledHeartbeat:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    client = RacingClient()
    errors: list[BaseException] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db, limit=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(
        ctx["aggregation"],
        "_FinalizationLeaseHeartbeat",
        DisabledHeartbeat,
    )
    ctx["aggregation"].set_llm_client_override(client)
    stale_worker = threading.Thread(target=finalize_in_thread, daemon=True)
    stale_worker.start()
    try:
        assert first_call_entered.wait(timeout=10), "first finalizer never reached provider"
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            stale_token = job.finalization_claim_token
            assert stale_token is not None
            job.finalization_lease_expires_at = (
                ctx["aggregation"]._now() - timedelta(seconds=1)
            )
            db.commit()

        with ctx["db_module"].SessionLocal() as db:
            assert ctx["aggregation"].finalize_ready_jobs(db, limit=1) == []
        assert client.calls == 2

        release_first_call.set()
        stale_worker.join(timeout=10)
        assert not stale_worker.is_alive(), "stale finalizer did not exit"
    finally:
        release_first_call.set()
        ctx["aggregation"].set_llm_client_override(None)
        stale_worker.join(timeout=10)

    assert errors == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "RUNNING"
        assert job.current_generation == 1
        assert job.finalization_claim_token is None
        assert job.finalization_claim_generation is None
        assert job.finalization_lease_expires_at is None
        generation_one_candidates = [
            candidate
            for candidate in job.candidates
            if candidate.generation_index == 1
        ]
        assert generation_one_candidates
        assert len({candidate.id for candidate in generation_one_candidates}) == len(
            generation_one_candidates
        )
        event_types = [event.event_type for event in job.events]
        assert event_types.count("generation_dispatched") == 1
        assert event_types.count("harness_decision_accepted") == 1
        assert event_types.count("harness_tool_execution_result") == 1
        assert "job_failed" not in event_types


def test_llm_harness_heartbeat_prevents_live_claim_takeover(
    gpt_ctx,
    monkeypatch,
) -> None:
    """A live provider call renews its explicit lease across DB sessions."""

    ctx = gpt_ctx
    job_id = _create_job(
        ctx,
        strategy="llm_harness",
        target_rmse=0.001,
        max_iterations=2,
    )
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "heartbeat-worker",
            )
        if trial_id is None:
            break

    entered = threading.Event()
    release = threading.Event()
    provider_wait_timeout_seconds = 30.0

    class BlockingClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
            self.calls += 1
            entered.set()
            if not release.wait(timeout=provider_wait_timeout_seconds):
                raise TimeoutError("test did not release provider call")
            return {
                "decision": {
                    "tool_id": "cma_es",
                    "rationale": "Use bounded evolutionary search.",
                }
            }

    client = BlockingClient()
    errors: list[BaseException] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db, limit=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(
        ctx["aggregation"],
        "get_settings",
        lambda: SimpleNamespace(
            finalization_lease_seconds=1,
            finalization_lease_heartbeat_seconds=0.05,
        ),
    )
    ctx["aggregation"].set_llm_client_override(client)
    worker = threading.Thread(target=finalize_in_thread, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=provider_wait_timeout_seconds), (
            "finalizer never reached provider"
        )
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            initial_token = job.finalization_claim_token
            initial_expiry = job.finalization_lease_expires_at
        assert initial_token is not None
        assert initial_expiry is not None

        time.sleep(0.2)
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            assert job.finalization_claim_token == initial_token
            assert job.finalization_lease_expires_at > initial_expiry
            assert ctx["aggregation"].finalize_ready_jobs(db, limit=1) == []
        assert client.calls == 1

        release.set()
        worker.join(timeout=10)
        assert not worker.is_alive(), "live finalizer did not finish"
    finally:
        release.set()
        ctx["aggregation"].set_llm_client_override(None)
        worker.join(timeout=10)

    assert errors == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "RUNNING"
        assert job.current_generation == 1
        assert job.finalization_claim_token is None
        event_types = [event.event_type for event in job.events]
        assert event_types.count("generation_dispatched") == 1
        assert event_types.count("harness_tool_execution_result") == 1


def test_stale_terminal_finalizer_cannot_publish_report_or_events(
    gpt_ctx,
    monkeypatch,
) -> None:
    """A reclaimed non-iterative finalizer is fenced before report storage."""

    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="heuristic", target_rmse=None)
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "stale-terminal-worker",
            )
        if trial_id is None:
            break

    class DisabledHeartbeat:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    first_rank_entered = threading.Event()
    release_first_rank = threading.Event()
    call_lock = threading.Lock()
    rank_calls = 0
    report_calls = 0
    original_rank = ctx["aggregation"]._rank_and_select_best
    original_report = ctx["aggregation"].report_generator.generate_and_persist_report

    def blocking_rank(candidates):
        nonlocal rank_calls
        with call_lock:
            rank_calls += 1
            call_number = rank_calls
        if call_number == 1:
            first_rank_entered.set()
            if not release_first_rank.wait(timeout=10):
                raise TimeoutError("test did not release stale terminal finalizer")
        return original_rank(candidates)

    def counted_report(*args, **kwargs):
        nonlocal report_calls
        with call_lock:
            report_calls += 1
        return original_report(*args, **kwargs)

    errors: list[BaseException] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db, limit=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(
        ctx["aggregation"],
        "_FinalizationLeaseHeartbeat",
        DisabledHeartbeat,
    )
    monkeypatch.setattr(ctx["aggregation"], "_rank_and_select_best", blocking_rank)
    monkeypatch.setattr(
        ctx["aggregation"].report_generator,
        "generate_and_persist_report",
        counted_report,
    )
    stale_worker = threading.Thread(target=finalize_in_thread, daemon=True)
    stale_worker.start()
    try:
        assert first_rank_entered.wait(timeout=10), "finalizer never reached terminal ranking"
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            job.finalization_lease_expires_at = (
                ctx["aggregation"]._now() - timedelta(seconds=1)
            )
            db.commit()
        with ctx["db_module"].SessionLocal() as db:
            assert ctx["aggregation"].finalize_ready_jobs(db, limit=1) == [job_id]

        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            before_release_event_ids = [event.id for event in job.events]
            before_release_artifact_ids = list(
                db.scalars(
                    select(ctx["models"].Artifact.id).where(
                        ctx["models"].Artifact.owner_type == "job",
                        ctx["models"].Artifact.owner_id == job_id,
                    )
                )
            )
            assert job.report is not None
        assert report_calls == 1

        release_first_rank.set()
        stale_worker.join(timeout=10)
        assert not stale_worker.is_alive(), "stale terminal finalizer did not exit"
    finally:
        release_first_rank.set()
        stale_worker.join(timeout=10)

    assert errors == []
    assert report_calls == 1
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "COMPLETED"
        assert job.finalization_claim_token is None
        assert [event.id for event in job.events] == before_release_event_ids
        assert list(
            db.scalars(
                select(ctx["models"].Artifact.id).where(
                    ctx["models"].Artifact.owner_type == "job",
                    ctx["models"].Artifact.owner_id == job_id,
                )
            )
        ) == before_release_artifact_ids
        event_types = [event.event_type for event in job.events]
        assert event_types.count("best_candidate_selected") == 1
        assert event_types.count("job_completed") == 1


def test_cancellation_fences_finalizer_before_report_publication(
    gpt_ctx,
    monkeypatch,
) -> None:
    """A committed cancellation clears the claim before a report can publish."""

    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="heuristic", target_rmse=None)
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "cancel-race-worker",
            )
        if trial_id is None:
            break

    class DisabledHeartbeat:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    rank_entered = threading.Event()
    release_rank = threading.Event()
    report_calls = 0
    original_rank = ctx["aggregation"]._rank_and_select_best
    original_report = ctx["aggregation"].report_generator.generate_and_persist_report

    def blocking_rank(candidates):
        rank_entered.set()
        if not release_rank.wait(timeout=10):
            raise TimeoutError("test did not release cancelled finalizer")
        return original_rank(candidates)

    def counted_report(*args, **kwargs):
        nonlocal report_calls
        report_calls += 1
        return original_report(*args, **kwargs)

    errors: list[BaseException] = []
    finalized: list[str] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                finalized.extend(ctx["aggregation"].finalize_ready_jobs(db, limit=1))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(
        ctx["aggregation"],
        "_FinalizationLeaseHeartbeat",
        DisabledHeartbeat,
    )
    monkeypatch.setattr(ctx["aggregation"], "_rank_and_select_best", blocking_rank)
    monkeypatch.setattr(
        ctx["aggregation"].report_generator,
        "generate_and_persist_report",
        counted_report,
    )
    finalizer = threading.Thread(target=finalize_in_thread, daemon=True)
    finalizer.start()
    try:
        assert rank_entered.wait(timeout=10), "finalizer never reached terminal ranking"
        with ctx["db_module"].SessionLocal() as db:
            cancelled = ctx["jobs_service"].cancel_job(db, job_id)
            assert cancelled.status == "CANCELLED"
            assert cancelled.finalization_claim_token is None

        release_rank.set()
        finalizer.join(timeout=10)
        assert not finalizer.is_alive(), "cancelled finalizer did not exit"
    finally:
        release_rank.set()
        finalizer.join(timeout=10)

    assert errors == []
    assert finalized == []
    assert report_calls == 0
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "CANCELLED"
        assert job.report is None
        assert job.finalization_claim_token is None
        assert job.finalization_claim_generation is None
        assert job.finalization_lease_expires_at is None
        event_types = [event.event_type for event in job.events]
        assert event_types.count("job_cancelled") == 1
        assert "best_candidate_selected" not in event_types
        assert "job_completed" not in event_types
        assert "job_failed" not in event_types


def test_stale_failure_finalizer_cannot_commit_failure_event(
    gpt_ctx,
    monkeypatch,
) -> None:
    """A reclaimed failure path cannot overwrite the current finalizer."""

    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="heuristic", target_rmse=None)
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "stale-failure-worker",
            )
        if trial_id is None:
            break
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        job.baseline_candidate_id = None
        db.commit()

    class DisabledHeartbeat:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    first_failure_entered = threading.Event()
    release_first_failure = threading.Event()
    call_lock = threading.Lock()
    failure_calls = 0
    original_fail = ctx["aggregation"]._fail_job

    def blocking_fail(*args, **kwargs):
        nonlocal failure_calls
        with call_lock:
            failure_calls += 1
            call_number = failure_calls
        if call_number == 1:
            first_failure_entered.set()
            if not release_first_failure.wait(timeout=10):
                raise TimeoutError("test did not release stale failure finalizer")
        return original_fail(*args, **kwargs)

    errors: list[BaseException] = []

    def finalize_in_thread() -> None:
        try:
            with ctx["db_module"].SessionLocal() as db:
                ctx["aggregation"].finalize_ready_jobs(db, limit=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(
        ctx["aggregation"],
        "_FinalizationLeaseHeartbeat",
        DisabledHeartbeat,
    )
    monkeypatch.setattr(ctx["aggregation"], "_fail_job", blocking_fail)
    stale_worker = threading.Thread(target=finalize_in_thread, daemon=True)
    stale_worker.start()
    try:
        assert first_failure_entered.wait(timeout=10), "finalizer never reached failure path"
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            job.finalization_lease_expires_at = (
                ctx["aggregation"]._now() - timedelta(seconds=1)
            )
            db.commit()
        with ctx["db_module"].SessionLocal() as db:
            assert ctx["aggregation"].finalize_ready_jobs(db, limit=1) == [job_id]
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            before_release_event_ids = [event.id for event in job.events]
            assert job.status == "FAILED"
            assert job.report is None

        release_first_failure.set()
        stale_worker.join(timeout=10)
        assert not stale_worker.is_alive(), "stale failure finalizer did not exit"
    finally:
        release_first_failure.set()
        stale_worker.join(timeout=10)

    assert errors == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "FAILED"
        assert job.latest_error_code == "BASELINE_MISSING"
        assert job.finalization_claim_token is None
        assert [event.id for event in job.events] == before_release_event_ids
        event_types = [event.event_type for event in job.events]
        assert event_types.count("job_failed") == 1


def test_heuristic_mode_still_finalizes_and_purges_secrets(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="heuristic", target_rmse=None)
    status = _drive(ctx, job_id, client=None, max_ticks=60)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimization_outcome in {"success", "no_usable_candidate"}
        assert all(s.deleted_at is not None for s in job.secrets)


def test_cma_es_loop_runs_baseline_then_dispatches_next_generation(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="cma_es", target_rmse=0.01, max_iterations=2)
    status = _drive(ctx, job_id, client=None, max_ticks=80)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.current_generation >= 1
        baseline = next(c for c in job.candidates if c.is_baseline)
        optimizer_candidates = [
            c for c in job.candidates if c.source_type == "optimizer" and not c.is_baseline
        ]
        assert baseline.generation_index == 0
        assert len(optimizer_candidates) >= 1
        assert all(c.label.startswith("cma_es_gen_") for c in optimizer_candidates)
        event_types = [e.event_type for e in job.events]
        assert "generation_dispatched" in event_types


def test_cma_es_max_iterations_reached_yields_best_so_far(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="cma_es", target_rmse=0.001, max_iterations=1)
    status = _drive(ctx, job_id, client=None, max_ticks=80)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.current_generation == 1
        assert job.optimization_outcome == "max_iterations_reached"
        assert job.report is not None


@pytest.mark.parametrize("strategy", ["cma_es", "gpt"])
def test_iterative_optimizer_without_stopping_target_uses_budget(gpt_ctx, strategy):
    ctx = gpt_ctx
    job_id = _create_job(
        ctx,
        strategy=strategy,
        target_rmse=None,
        min_pass_rate=0.0,
        max_iterations=1,
    )
    client = (
        FakeOpenAIClient([_gpt_proposal(1.5)])
        if strategy == "gpt"
        else None
    )

    assert _drive(ctx, job_id, client=client, max_ticks=80) == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.current_generation == 1
        assert len([candidate for candidate in job.candidates if not candidate.is_baseline]) == 1


def test_acceptance_evaluator_checks_thresholds(gpt_ctx):
    ctx = gpt_ctx
    models_mod = ctx["models"]
    schemas = ctx["schemas"]
    acceptance = ctx["acceptance"]

    class DummyJob:
        target_rmse = 0.5
        target_max_error = 1.5
        min_pass_rate = 0.8

    criteria = acceptance.criteria_for_job(DummyJob())
    candidate = models_mod.CandidateParameterSet(
        id="c1",
        job_id="j1",
        generation_index=1,
        source_type="optimizer",
        label="x",
        parameter_json={},
        trial_count=4,
        completed_trial_count=4,
        failed_trial_count=0,
        # Phase 8 polish: pass_rate is driven by passing_trial_count (trials
        # with per-trial pass_flag=true), not the execution-completion ratio.
        # All 4 trials pass_flag=true -> pass_rate=1.0 ≥ 0.8.
        aggregated_metric_json={
            "rmse": 0.3,
            "max_error": 1.0,
            "passing_trial_count": 4,
        },
    )
    assert acceptance.evaluate_candidate(candidate, criteria).passed
    candidate.aggregated_metric_json = {
        "rmse": 0.9,
        "max_error": 1.0,
        "passing_trial_count": 4,
    }
    assert not acceptance.evaluate_candidate(candidate, criteria).passed
    candidate.aggregated_metric_json = {
        "rmse": 0.3,
        "max_error": 2.0,
        "passing_trial_count": 4,
    }
    assert not acceptance.evaluate_candidate(candidate, criteria).passed
    # Phase 8 polish: thresholds all satisfied but only 2/4 trials actually
    # passed (pass_flag=true), so pass_rate=0.5 < min_pass_rate=0.8 -> reject.
    candidate.aggregated_metric_json = {
        "rmse": 0.3,
        "max_error": 1.0,
        "passing_trial_count": 2,
    }
    failed = acceptance.evaluate_candidate(candidate, criteria)
    assert not failed.passed
    assert failed.reason == "pass_rate_too_low"
    assert failed.pass_rate == 0.5
    assert failed.completion_rate == 1.0
    assert schemas.AcceptanceCriteria(
        target_rmse=0.5, target_max_error=1.5, min_pass_rate=0.8
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
