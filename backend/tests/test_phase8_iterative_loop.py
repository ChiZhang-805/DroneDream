"""Phase 8 tests for the iterative GPT tuning loop and acceptance evaluator."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import pytest


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
            target_rmse=target_rmse, min_pass_rate=0.5
        ),
        openai=(
            schemas.OpenAIConfig(api_key="sk-iterative-test") if strategy == "gpt" else None
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
        event_types = [e.event_type for e in job.events]
        assert "llm_proposal_started" in event_types
        assert "generation_dispatched" in event_types
        assert "candidate_generated_from_llm" in event_types


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


def test_gpt_failure_falls_through_to_best_so_far(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="gpt", target_rmse=0.001, max_iterations=3)
    client = FakeOpenAIClient([RuntimeError("openai is down")])
    status = _drive(ctx, job_id, client=client, max_ticks=60)
    assert status == "FAILED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimization_outcome in {
            "llm_failed",
            "no_usable_candidate",
            "max_iterations_reached",
        }
        event_types = [e.event_type for e in job.events]
        assert "llm_proposal_failed" in event_types


def test_heuristic_mode_still_finalizes_and_purges_secrets(gpt_ctx):
    ctx = gpt_ctx
    job_id = _create_job(ctx, strategy="heuristic", target_rmse=None)
    status = _drive(ctx, job_id, client=None, max_ticks=60)
    assert status == "COMPLETED"
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.optimization_outcome in {"success", "no_usable_candidate"}
        assert all(s.deleted_at is not None for s in job.secrets)


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
