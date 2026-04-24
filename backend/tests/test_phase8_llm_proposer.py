"""Phase 8 tests for the GPT parameter proposer (with mocked OpenAI client)."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any

import pytest


class FakeOpenAIClient:
    """Minimal stand-in implementing the :class:`OpenAIClientLike` protocol."""

    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        self.calls.append({"model": model, "system": system, "user": user})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture()
def llm_ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    db_path = tmp_path / "llm.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-key")
    from app import config as config_module

    config_module.get_settings.cache_clear()

    # Evict every cached `app.*` module so the fresh engine/metadata cannot be
    # polluted by earlier tests that imported models against the original Base.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    import app.db as db_module  # type: ignore[import-not-found]
    import app.models as models_module  # type: ignore[import-not-found]
    import app.orchestration.acceptance as acceptance_module  # type: ignore[import-not-found]
    import app.orchestration.llm_parameter_proposer as proposer_module  # type: ignore[import-not-found]
    import app.services.jobs as jobs_service_module  # type: ignore[import-not-found]  # noqa: I001

    db_module.init_db()

    yield {
        "db_module": db_module,
        "models": models_module,
        "schemas": __import__("app.schemas", fromlist=["*"]),
        "jobs_service": jobs_service_module,
        "acceptance": acceptance_module,
        "proposer": proposer_module,
    }

    config_module.get_settings.cache_clear()


def _create_gpt_job(ctx: dict[str, object], *, with_secret: bool = True) -> str:
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    req = schemas.JobCreateRequest(
        simulator_backend="mock",
        optimizer_strategy="gpt",
        max_iterations=3,
        trials_per_candidate=2,
        acceptance_criteria=schemas.AcceptanceCriteria(target_rmse=0.5, min_pass_rate=0.5),
        openai=(
            schemas.OpenAIConfig(api_key="sk-test-unit", model="gpt-4.1")
            if with_secret
            else None
        ),
    )
    with db_module.SessionLocal() as db:
        job = jobs_service.create_job(db, req)
        return job.id


def test_proposer_records_events_and_clamps_output(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)

    fake = FakeOpenAIClient(
        {
            "proposals": [
                {
                    "label": "aggressive",
                    "rationale": "Increase kp to tighten tracking",
                    "parameters": {
                        "kp_xy": 99.0,  # will be clamped to 2.5
                        "kd_xy": -1.0,  # clamped up to 0.05
                        "ki_xy": 0.1,
                        "vel_limit": 5.0,
                        "accel_limit": 4.0,
                        "disturbance_rejection": 0.5,
                    },
                },
                {
                    "label": "conservative",
                    "rationale": "Smaller gains",
                    "parameters": {
                        "kp_xy": 0.9,
                        "kd_xy": 0.25,
                        "ki_xy": 0.05,
                        "vel_limit": 4.0,
                        "accel_limit": 3.0,
                        "disturbance_rejection": 0.6,
                    },
                },
            ]
        }
    )

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        seeded_candidate = ctx["models"].CandidateParameterSet(
            job_id=job_id,
            generation_index=0,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0, "kd_xy": 0.2, "ki_xy": 0.05},
            is_baseline=True,
            trial_count=1,
            completed_trial_count=1,
            aggregated_metric_json={
                "rmse": 0.9,
                "max_error": 1.4,
                "passing_trial_count": 1,
            },
            aggregated_score=0.9,
        )
        db.add(seeded_candidate)
        db.flush()
        seeded_trial = ctx["models"].Trial(
            job_id=job_id,
            candidate_id=seeded_candidate.id,
            seed=101,
            scenario_type="nominal",
            status="COMPLETED",
        )
        db.add(seeded_trial)
        db.flush()
        db.add(
            ctx["models"].TrialMetric(
                trial_id=seeded_trial.id,
                score=0.9,
                rmse=0.9,
                max_error=1.4,
                overshoot_count=1,
                completion_time=9.5,
                crash_flag=False,
                timeout_flag=False,
                final_error=0.2,
                pass_flag=True,
                instability_flag=False,
            )
        )
        db.flush()
        criteria = ctx["acceptance"].criteria_for_job(job)
        result = ctx["proposer"].propose_candidates(db, job, criteria, client=fake)
        db.commit()
        assert result.error is None
        assert len(result.proposals) == 1
        first = result.proposals[0]
        assert first.parameters["kp_xy"] == 2.5
        assert first.parameters["kd_xy"] == 0.05
        events = [
            e.event_type
            for e in db.scalars(
                __import__("sqlalchemy").select(ctx["models"].JobEvent).where(
                    ctx["models"].JobEvent.job_id == job_id
                )
            )
        ]
        assert "llm_proposal_started" in events
        assert "llm_proposal_completed" in events
        payload = json.loads(fake.calls[0]["user"])
        assert len(payload["previous_candidates"]) >= 1
        assert any("trials" in candidate for candidate in payload["previous_candidates"])


def test_proposer_rejects_invalid_response(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)
    fake = FakeOpenAIClient({"not_proposals": [1, 2, 3]})
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        criteria = ctx["acceptance"].criteria_for_job(job)
        result = ctx["proposer"].propose_candidates(db, job, criteria, client=fake)
        db.commit()
        assert result.error == "invalid_response"
        assert result.proposals == []


def test_proposer_handles_client_exception(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)
    fake = FakeOpenAIClient(RuntimeError("upstream 500"))
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        criteria = ctx["acceptance"].criteria_for_job(job)
        result = ctx["proposer"].propose_candidates(db, job, criteria, client=fake)
        db.commit()
        assert result.error is not None
        assert "upstream 500" in result.error
        events = [
            e.event_type
            for e in db.scalars(
                __import__("sqlalchemy").select(ctx["models"].JobEvent).where(
                    ctx["models"].JobEvent.job_id == job_id
                )
            )
        ]
        assert "llm_proposal_failed" in events


def test_proposer_rejects_nan_or_extra_keys(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)
    fake = FakeOpenAIClient(
        {
            "proposals": [
                {
                    "label": "bad",
                    "rationale": "nan",
                    "parameters": {
                        "kp_xy": float("nan"),
                        "kd_xy": 0.2,
                        "ki_xy": 0.05,
                        "vel_limit": 5.0,
                        "accel_limit": 4.0,
                        "disturbance_rejection": 0.5,
                    },
                }
            ]
        }
    )
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        criteria = ctx["acceptance"].criteria_for_job(job)
        result = ctx["proposer"].propose_candidates(db, job, criteria, client=fake)
        db.commit()
        assert result.error == "invalid_response"


def test_create_job_rejects_gpt_without_api_key(llm_ctx):
    ctx = llm_ctx
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    req = schemas.JobCreateRequest(
        optimizer_strategy="gpt",
    )
    with db_module.SessionLocal() as db:
        with pytest.raises(jobs_service.JobServiceError) as exc:
            jobs_service.create_job(db, req)
        assert exc.value.code == "INVALID_INPUT"


def test_job_create_request_defaults_are_gpt_and_20(llm_ctx):
    schemas = llm_ctx["schemas"]
    req = schemas.JobCreateRequest()
    assert req.optimizer_strategy == "gpt"
    assert req.max_iterations == 20


def test_secret_is_never_returned_in_job_response(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    with db_module.SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        resp = jobs_service.to_job_schema(job).model_dump()
    flat = repr(resp)
    assert "sk-test-unit" not in flat


def test_job_response_exposes_phase8_fields(llm_ctx):
    ctx = llm_ctx
    job_id = _create_gpt_job(ctx)
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]
    with db_module.SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        resp = jobs_service.to_job_schema(job).model_dump()
    assert resp["simulator_backend_requested"] == "mock"
    assert resp["optimizer_strategy"] == "gpt"
    assert resp["max_iterations"] == 3
    assert resp["trials_per_candidate"] == 2
    assert resp["acceptance_criteria"]["target_rmse"] == 0.5
    assert resp["current_generation"] == 0
    assert resp["optimization_outcome"] is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
