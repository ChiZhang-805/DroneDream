"""Phase 4 tests: SimulatorAdapter abstraction + worker wiring.

These tests exercise the adapter directly (no DB) and the trial executor with
an injected adapter (with DB) so we can assert the worker calls through the
adapter rather than hardcoding simulator logic.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest

from app.simulator import (
    ArtifactMetadata,
    JobConfig,
    MockSimulatorAdapter,
    RealSimulatorAdapterStub,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialMetricsPayload,
    TrialResult,
    get_simulator_adapter,
)
from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_SIM_ERROR,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
)
from app.simulator.factory import UnknownSimulatorBackendError

# --- Helpers ---------------------------------------------------------------


def _make_ctx(
    *,
    scenario: str = "nominal",
    seed: int = 101,
    parameters: dict | None = None,
    scenario_config: dict | None = None,
    sensor_noise_level: str = "medium",
    wind: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> TrialContext:
    job_config = JobConfig(
        track_type="circle",
        start_point_x=0.0,
        start_point_y=0.0,
        altitude_m=3.0,
        wind_north=wind[0],
        wind_east=wind[1],
        wind_south=wind[2],
        wind_west=wind[3],
        sensor_noise_level=sensor_noise_level,
        objective_profile="robust",
    )
    return TrialContext(
        trial_id="tri_test",
        job_id="job_test",
        job_config=job_config,
        candidate_id="cand_test",
        parameters=parameters
        or {
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": 5.0,
            "accel_limit": 4.0,
            "disturbance_rejection": 0.5,
        },
        seed=seed,
        scenario_type=scenario,
        scenario_config=scenario_config,
    )


# --- MockSimulatorAdapter --------------------------------------------------


def test_mock_adapter_is_deterministic_for_same_inputs():
    adapter = MockSimulatorAdapter()
    ctx = _make_ctx(scenario="nominal", seed=101)

    r1 = adapter.run_trial(ctx)
    r2 = adapter.run_trial(ctx)

    assert r1.success and r2.success
    assert r1.metrics is not None and r2.metrics is not None
    assert r1.metrics.as_dict() == r2.metrics.as_dict()


def test_mock_adapter_scenario_worsens_rmse():
    adapter = MockSimulatorAdapter()
    nominal = adapter.run_trial(_make_ctx(scenario="nominal", seed=101))
    noise = adapter.run_trial(_make_ctx(scenario="noise_perturbed", seed=101))
    wind = adapter.run_trial(_make_ctx(scenario="wind_perturbed", seed=101))
    combined = adapter.run_trial(_make_ctx(scenario="combined_perturbed", seed=101))

    assert nominal.metrics is not None
    assert noise.metrics is not None
    assert wind.metrics is not None
    assert combined.metrics is not None

    # The factor table is strictly increasing, so each scenario should have
    # a strictly higher rmse than nominal at the same seed.
    assert noise.metrics.rmse > nominal.metrics.rmse
    assert wind.metrics.rmse > nominal.metrics.rmse
    assert combined.metrics.rmse > wind.metrics.rmse


def test_mock_adapter_wind_and_noise_affect_metrics():
    adapter = MockSimulatorAdapter()
    calm = adapter.run_trial(
        _make_ctx(scenario="wind_perturbed", seed=303, sensor_noise_level="low")
    )
    stormy = adapter.run_trial(
        _make_ctx(
            scenario="wind_perturbed",
            seed=303,
            sensor_noise_level="high",
            wind=(5.0, 2.0, 0.0, 0.0),
        )
    )

    assert calm.metrics is not None and stormy.metrics is not None
    assert stormy.metrics.rmse > calm.metrics.rmse


def test_mock_adapter_returns_artifact_metadata():
    adapter = MockSimulatorAdapter()
    result = adapter.run_trial(_make_ctx())

    assert result.success
    types = {a.artifact_type for a in result.artifacts}
    assert types == {"trajectory_plot", "telemetry_json", "worker_log"}
    for artifact in result.artifacts:
        assert isinstance(artifact, ArtifactMetadata)
        assert artifact.storage_path.startswith("mock://trials/")
        assert artifact.display_name  # non-empty


def test_mock_adapter_metrics_payload_fields_complete():
    adapter = MockSimulatorAdapter()
    result = adapter.run_trial(_make_ctx())

    assert result.metrics is not None
    metrics: TrialMetricsPayload = result.metrics
    payload = metrics.as_dict()
    expected_keys = {
        "rmse",
        "max_error",
        "overshoot_count",
        "completion_time",
        "crash_flag",
        "timeout_flag",
        "score",
        "final_error",
        "pass_flag",
        "instability_flag",
        "raw_metric_json",
    }
    assert expected_keys.issubset(payload.keys())
    raw = payload["raw_metric_json"]
    assert raw["track_type"] == "circle"
    assert raw["reference_track_point_count"] == 0


def test_mock_adapter_includes_advanced_scenario_summary():
    adapter = MockSimulatorAdapter()
    result = adapter.run_trial(
        _make_ctx(
            scenario="combined_perturbed",
            scenario_config={
                "advanced_scenario_config": {
                    "wind_gusts": {
                        "enabled": True,
                        "magnitude_mps": 3.0,
                        "direction_deg": 10,
                        "period_s": 4,
                    },
                    "sensor_degradation": {"dropout_rate": 0.6},
                    "battery": {"initial_percent": 75, "voltage_sag": True, "mass_payload_kg": 3.0},
                    "obstacles": [{"type": "cylinder"}],
                }
            },
        )
    )
    assert result.metrics is not None
    raw = result.metrics.raw_metric_json
    assert raw["advanced_scenario_summary"]["has_advanced"] is True
    assert raw["advanced_scenario_summary"]["gust_enabled"] is True
    assert raw["advanced_scenario_summary"]["dropout_instability_risk"] == "high"


@pytest.mark.parametrize(
    ("inject", "expected_code"),
    [
        ("timeout", FAILURE_TIMEOUT),
        ("simulation_failed", FAILURE_SIMULATION),
        ("unstable_candidate", FAILURE_UNSTABLE),
    ],
)
def test_mock_adapter_failure_injection_via_scenario_config(inject, expected_code):
    adapter = MockSimulatorAdapter()
    ctx = _make_ctx(scenario_config={"inject_failure": inject})
    result = adapter.run_trial(ctx)

    assert result.success is False
    assert result.metrics is None
    assert result.failure is not None
    assert result.failure.code == expected_code
    assert result.log_excerpt is not None


def test_mock_adapter_failure_injection_via_parameters():
    adapter = MockSimulatorAdapter()
    ctx = _make_ctx(parameters={"kp_xy": 1.0, "inject_failure": "timeout"})

    result = adapter.run_trial(ctx)

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_TIMEOUT


def test_mock_adapter_ignores_unknown_failure_code():
    adapter = MockSimulatorAdapter()
    ctx = _make_ctx(scenario_config={"inject_failure": "not_a_real_code"})
    result = adapter.run_trial(ctx)
    assert result.success is True
    assert result.metrics is not None


# --- RealSimulatorAdapterStub ----------------------------------------------


def test_real_stub_returns_structured_unavailable_result():
    adapter = RealSimulatorAdapterStub()
    result = adapter.run_trial(_make_ctx())

    assert result.success is False
    assert result.backend == "real_stub"
    assert result.failure is not None
    assert result.failure.code == FAILURE_ADAPTER_UNAVAILABLE
    assert "mock" in result.failure.reason.lower() or "real" in result.failure.reason.lower()


def test_real_stub_can_be_configured_to_raise():
    adapter = RealSimulatorAdapterStub()
    adapter.raise_on_run = True
    with pytest.raises(NotImplementedError):
        adapter.run_trial(_make_ctx())


# --- Factory --------------------------------------------------------------


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    adapter = get_simulator_adapter()
    assert isinstance(adapter, MockSimulatorAdapter)
    assert adapter.backend_name == "mock"


def test_factory_respects_env_var(monkeypatch):
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_stub")
    adapter = get_simulator_adapter()
    assert isinstance(adapter, RealSimulatorAdapterStub)


def test_factory_explicit_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_stub")
    adapter = get_simulator_adapter("mock")
    assert isinstance(adapter, MockSimulatorAdapter)


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("SIMULATOR_BACKEND", "gazebo_v9000")
    with pytest.raises(UnknownSimulatorBackendError):
        get_simulator_adapter()


# --- Worker-level wiring ---------------------------------------------------


@pytest.fixture()
def orchestration_ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    """Isolated DB + reloaded orchestration modules, mirroring test_orchestration."""

    db_path = tmp_path / "orch.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")

    from app import config as config_module

    config_module.get_settings.cache_clear()

    import app.db as db_module

    importlib.reload(db_module)

    import app.models as models_module

    importlib.reload(models_module)

    import app.services.jobs as jobs_service_module

    importlib.reload(jobs_service_module)

    import app.orchestration.aggregation as aggregation_module
    import app.orchestration.events as events_module
    import app.orchestration.job_manager as job_manager_module
    import app.orchestration.runner as runner_module
    import app.orchestration.trial_executor as trial_executor_module

    importlib.reload(events_module)
    importlib.reload(job_manager_module)
    importlib.reload(trial_executor_module)
    importlib.reload(aggregation_module)
    importlib.reload(runner_module)

    db_module.init_db()

    yield {
        "db_module": db_module,
        "models": models_module,
        "schemas": __import__("app.schemas", fromlist=["*"]),
        "jobs_service": jobs_service_module,
        "job_manager": job_manager_module,
        "trial_executor": trial_executor_module,
    }

    config_module.get_settings.cache_clear()


def _create_queued_job(ctx):
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            ctx["schemas"].JobCreateRequest(
                optimizer_strategy="heuristic",
                simulator_backend="mock",
            ),
        )
        return job.id


class _RecordingAdapter(SimulatorAdapter):
    """Adapter that records every call so tests can assert wiring."""

    backend_name = "recording"

    def __init__(self, delegate: SimulatorAdapter) -> None:
        self.delegate = delegate
        self.calls: list[str] = []
        self.contexts: list[TrialContext] = []

    def prepare(self, ctx: TrialContext) -> None:
        self.calls.append("prepare")

    def run_trial(self, ctx: TrialContext) -> TrialResult:
        self.calls.append("run_trial")
        self.contexts.append(ctx)
        return self.delegate.run_trial(ctx)

    def cleanup(self, ctx: TrialContext) -> None:
        self.calls.append("cleanup")


def test_worker_uses_adapter_not_hardcoded_logic(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        ctx["job_manager"].start_queued_jobs(db)

    adapter = _RecordingAdapter(MockSimulatorAdapter())
    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db, "test-worker", adapter=adapter
        )

    assert trial_id is not None
    # Adapter lifecycle was actually invoked.
    assert adapter.calls == ["prepare", "run_trial", "cleanup"]
    # The context carried the full set of Phase-4-required inputs.
    invocation = adapter.contexts[0]
    assert invocation.trial_id == trial_id
    assert invocation.job_id == job_id
    assert invocation.candidate_id
    assert invocation.scenario_type in {
        "nominal",
        "noise_perturbed",
        "wind_perturbed",
        "combined_perturbed",
    }
    assert isinstance(invocation.parameters, dict)
    assert invocation.seed > 0

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial.status == "COMPLETED"
        # simulator_backend is taken from the adapter, not hardcoded.
        assert trial.simulator_backend == "recording"
        # Artifact metadata produced by the adapter was persisted.
        artifacts = (
            db.query(ctx["models"].Artifact)
            .filter(
                ctx["models"].Artifact.owner_type == "trial",
                ctx["models"].Artifact.owner_id == trial_id,
            )
            .all()
        )
        assert {a.artifact_type for a in artifacts} == {
            "trajectory_plot",
            "telemetry_json",
            "worker_log",
        }


def test_worker_marks_trial_failed_when_adapter_returns_failure(orchestration_ctx):
    ctx = orchestration_ctx
    _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        ctx["job_manager"].start_queued_jobs(db)

    class _AlwaysTimeout(SimulatorAdapter):
        backend_name = "always_timeout"

        def run_trial(self, _ctx: TrialContext) -> TrialResult:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=FAILURE_TIMEOUT, reason="injected"),
                log_excerpt="[test] timeout",
            )

    adapter = _AlwaysTimeout()
    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db, "test-worker", adapter=adapter
        )

    assert trial_id is not None
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial.status == "FAILED"
        assert trial.failure_code == FAILURE_TIMEOUT
        assert trial.failure_reason == "injected"
        assert trial.simulator_backend == "always_timeout"
        # No metric row for a failed trial.
        assert trial.metric is None
        # Trial failure still advances the parent job's progress counter.
        job = db.get(ctx["models"].Job, trial.job_id)
        assert job.progress_completed_trials == 1


def test_worker_marks_trial_failed_when_adapter_raises(orchestration_ctx):
    ctx = orchestration_ctx
    _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        ctx["job_manager"].start_queued_jobs(db)

    class _Crash(SimulatorAdapter):
        backend_name = "crasher"

        def run_trial(self, _ctx: TrialContext) -> TrialResult:
            raise RuntimeError("boom")

    adapter = _Crash()
    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db, "test-worker", adapter=adapter
        )

    assert trial_id is not None
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial.status == "FAILED"
        assert trial.failure_code == FAILURE_SIM_ERROR
        assert "boom" in (trial.failure_reason or "")


# --- Phase 8: backend precedence helper --------------------------------------


def test_resolve_backend_override_env_wins(monkeypatch):
    """SIMULATOR_BACKEND env var overrides the per-job column."""

    from app.orchestration.trial_executor import _resolve_backend_override

    assert (
        _resolve_backend_override(
            env_backend="mock", job_backend_requested="real_cli"
        )
        == "mock"
    )


def test_resolve_backend_override_falls_back_to_job_column():
    """With env var blank/unset, the job's simulator_backend_requested is used."""

    from app.orchestration.trial_executor import _resolve_backend_override

    assert (
        _resolve_backend_override(
            env_backend=None, job_backend_requested="real_cli"
        )
        == "real_cli"
    )


def test_resolve_backend_override_returns_none_when_neither_set():
    """With neither source set, return None so the factory default applies."""

    from app.orchestration.trial_executor import _resolve_backend_override

    assert (
        _resolve_backend_override(env_backend=None, job_backend_requested=None)
        is None
    )


def test_env_simulator_backend_treats_blank_as_unset(monkeypatch):
    """.env.example ships SIMULATOR_BACKEND= (empty). This must behave like unset
    so per-job UI selection from the New Job form takes effect by default."""

    from app.orchestration.trial_executor import _env_simulator_backend

    monkeypatch.setenv("SIMULATOR_BACKEND", "")
    assert _env_simulator_backend() is None

    monkeypatch.setenv("SIMULATOR_BACKEND", "   ")
    assert _env_simulator_backend() is None

    monkeypatch.setenv("SIMULATOR_BACKEND", "real_cli")
    assert _env_simulator_backend() == "real_cli"

    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    assert _env_simulator_backend() is None
