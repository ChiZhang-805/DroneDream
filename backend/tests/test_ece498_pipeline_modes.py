from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


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

    import app.db as db_module
    import app.models as models_module
    import app.orchestration.aggregation as aggregation
    import app.orchestration.runner as runner
    import app.services.jobs as jobs_service

    db_module.init_db()
    yield {"db_module": db_module, "models": models_module, "schemas": __import__("app.schemas", fromlist=["*"]), "jobs_service": jobs_service, "aggregation": aggregation, "runner": runner}
    config_module.get_settings.cache_clear()


def _create_job(ctx: dict[str, object], *, strategy: str, target_rmse: float | None, max_iterations: int) -> str:
    schemas = ctx["schemas"]
    req = schemas.JobCreateRequest(simulator_backend="mock", optimizer_strategy=strategy, max_iterations=max_iterations, trials_per_candidate=2, acceptance_criteria=schemas.AcceptanceCriteria(target_rmse=target_rmse, min_pass_rate=0.5), openai=(schemas.OpenAIConfig(api_key="sk") if strategy == "gpt" else None))
    with ctx["db_module"].SessionLocal() as db:
        return ctx["jobs_service"].create_job(db, req).id


def _drive(ctx: dict[str, object], job_id: str, *, max_ticks: int = 100):
    for _ in range(max_ticks):
        ctx["runner"].tick("iter-worker")
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                return job.status
    return None


def test_none_strategy_only_dispatches_baseline(gpt_ctx):
    job_id = _create_job(gpt_ctx, strategy="none", target_rmse=None, max_iterations=1)
    assert _drive(gpt_ctx, job_id) == "COMPLETED"


def test_cma_es_one_generation_dispatches_gen1(gpt_ctx):
    job_id = _create_job(gpt_ctx, strategy="cma_es", target_rmse=0.001, max_iterations=1)
    assert _drive(gpt_ctx, job_id) == "COMPLETED"


def test_cma_es_max_three_generations(gpt_ctx):
    job_id = _create_job(gpt_ctx, strategy="cma_es", target_rmse=0.0001, max_iterations=3)
    assert _drive(gpt_ctx, job_id) == "COMPLETED"
