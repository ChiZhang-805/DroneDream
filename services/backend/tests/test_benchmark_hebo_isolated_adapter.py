from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.contracts import (
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    canonical_sha256,
)
from app.benchmarking.hebo_isolated_adapter import (
    HEBO_RUNNER_PROTOCOL_VERSION,
    HeboIsolatedAdapterV1,
    HeboRunnerRequestV1,
    HeboRunnerResponseV1,
    JsonSubprocessHeboRunnerV1,
    build_hebo_runner_request,
)
from app.benchmarking.hebo_reference_contract import (
    HEBO_DISTRIBUTION_LOCK_SHA256,
    HEBO_POLICY_SHA256,
)

ENVIRONMENT_SHA256 = "e" * 64


def _objective(*, loss: float, feasible: bool) -> BenchmarkOptimizerOutcomeV1:
    return BenchmarkOptimizerOutcomeV1(
        role="objective",
        loss=loss,
        objectives={"tracking_error": loss},
        objective_directions={"tracking_error": "minimize"},
        constraint_violations={"safety": 0.0 if feasible else 1.0},
        feasible=feasible,
        failure_rate=0.0 if feasible else 1.0,
        completed=True,
    )


def _unsafe() -> BenchmarkOptimizerOutcomeV1:
    return BenchmarkOptimizerOutcomeV1(
        role="constraint_only",
        loss=None,
        objectives={},
        objective_directions={},
        constraint_violations={"safety": 1.0},
        feasible=False,
        failure_rate=1.0,
        completed=True,
    )


def _observation(*, with_history: bool = True) -> BenchmarkObservationV2:
    history = []
    if with_history:
        history = [
            BenchmarkHistoryItemV2(
                candidate_ref="candidate-1",
                generation_index=1,
                dispatch_ordinal=1,
                parameters={"kp": 1.0, "kd": 0.2, "mode": 1.0},
                screening_status="passed",
                outcome=_objective(loss=0.4, feasible=True),
            ),
            BenchmarkHistoryItemV2(
                candidate_ref="candidate-2",
                generation_index=2,
                dispatch_ordinal=2,
                parameters={"kp": 1.5, "kd": 0.3, "mode": 2.0},
                screening_status="unsafe",
                outcome=_unsafe(),
                failure_code="unsafe-flight",
            ),
        ]
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id="hebo",
        generation_index=3,
        next_dispatch_ordinal=len(history) + 1,
        algorithm_seed=20260805,
        simulator_seed_block_id="crn-1",
        parameter_domain=[
            {"name": "kp", "baseline": 1.0, "minimum": 0.5, "maximum": 2.0},
            {
                "name": "kd",
                "baseline": 0.2,
                "minimum": 0.05,
                "maximum": 0.5,
                "scale": "log",
            },
            {
                "name": "mode",
                "baseline": 1.0,
                "minimum": 0.0,
                "maximum": 2.0,
                "value_type": "enum",
                "choices": [0.0, 1.0, 2.0],
            },
        ],
        objectives=[{"name": "tracking_error", "direction": "minimize"}],
        constraints=[{"name": "safety", "operator": "le", "threshold": 0.0}],
        history=history,
        failure_semantics={"unsafe": "competing_terminal_event"},
        simulator_budget_remaining=8,
        wall_time_remaining_ms=60_000,
    )


def _response(
    request: HeboRunnerRequestV1,
    *,
    parameters: dict[str, float] | None = None,
    request_sha256: str | None = None,
    environment_sha256: str = ENVIRONMENT_SHA256,
    observed_feasible_count: int | None = None,
) -> HeboRunnerResponseV1:
    payload = {
        "schema_id": "dronedream.benchmark-hebo-runner-response/v1",
        "protocol_version": HEBO_RUNNER_PROTOCOL_VERSION,
        "adapter_id": "hebo/v1",
        "status": "proposed",
        "request_sha256": request_sha256 or request.request_sha256,
        "runner_environment_sha256": environment_sha256,
        "distribution_lock_sha256": HEBO_DISTRIBUTION_LOCK_SHA256,
        "policy_sha256": HEBO_POLICY_SHA256,
        "observed_feasible_count": (
            len(request.feasible_history)
            if observed_feasible_count is None
            else observed_feasible_count
        ),
        "sobol_draws_consumed": request.sobol_draws_consumed,
        "parameters": parameters or {"kp": 1.2, "kd": 0.25, "mode": 0.0},
    }
    return HeboRunnerResponseV1.model_validate(
        {**payload, "response_sha256": canonical_sha256(payload)}
    )


@dataclass(frozen=True)
class _FakeRunner:
    parameters: dict[str, float] | None = None
    wrong_request: bool = False
    wrong_environment: bool = False
    wrong_observation_count: bool = False
    runner_environment_sha256: str = ENVIRONMENT_SHA256

    def invoke(self, request: HeboRunnerRequestV1) -> HeboRunnerResponseV1:
        return _response(
            request,
            parameters=self.parameters,
            request_sha256="a" * 64 if self.wrong_request else None,
            environment_sha256=("b" * 64 if self.wrong_environment else ENVIRONMENT_SHA256),
            observed_feasible_count=(
                len(request.feasible_history) + 1 if self.wrong_observation_count else None
            ),
        )


def test_request_replays_only_real_feasible_losses_and_hashes_every_exclusion() -> None:
    observation = _observation()
    request = build_hebo_runner_request(observation)

    assert request.observation_sha256 == canonical_sha256(observation)
    assert request.next_trial_number == 2
    assert request.sobol_draws_consumed == 2
    assert request.excluded_outcome_count == 1
    assert len(request.feasible_history) == 1
    assert request.feasible_history[0].loss == 0.4
    assert request.feasible_history[0].candidate_ref == "candidate-1"
    assert "unsafe-flight" not in str(request.model_dump(mode="json"))
    assert "holdout" not in str(request.model_dump(mode="json")).lower()
    assert (
        canonical_sha256(request.model_dump(mode="json", exclude={"request_sha256"}))
        == request.request_sha256
    )


def test_adapter_returns_one_bounded_unseen_content_addressed_proposal() -> None:
    observation = _observation()
    adapter = HeboIsolatedAdapterV1(_FakeRunner())

    first = adapter.propose(observation)
    second = adapter.propose(observation)

    assert first == second
    assert first.candidate_ref.startswith("hebo-")
    assert first.parameters == {"kp": 1.2, "kd": 0.25, "mode": 0.0}
    assert first.proposal_receipt["method_classification"] == "standard_reference"
    assert first.proposal_receipt["observed_feasible_count"] == 1
    assert first.proposal_receipt["excluded_outcome_count"] == 1
    assert first.proposal_receipt["provider_access"] is False
    assert first.proposal_receipt["holdout_visibility"] == "sealed"


@pytest.mark.parametrize(
    "runner, message",
    (
        (_FakeRunner(wrong_request=True), "another request"),
        (_FakeRunner(wrong_environment=True), "environment identity differs"),
        (_FakeRunner(wrong_observation_count=True), "different feasible history"),
        (_FakeRunner(parameters={"kp": 9.0, "kd": 0.25, "mode": 0.0}), "outside"),
        (_FakeRunner(parameters={"kp": 1.0, "kd": 0.2, "mode": 1.0}), "repeated"),
    ),
)
def test_adapter_fails_closed_on_runner_drift_or_unsafe_output(
    runner: _FakeRunner, message: str
) -> None:
    with pytest.raises(BenchmarkAdapterError, match=message):
        HeboIsolatedAdapterV1(runner).propose(_observation())


def test_request_or_response_hash_tamper_is_rejected() -> None:
    request = build_hebo_runner_request(_observation())
    request_payload = request.model_dump(mode="python")
    request_payload["algorithm_seed"] += 1
    with pytest.raises(ValidationError, match="request hash"):
        HeboRunnerRequestV1.model_validate(request_payload)

    response = _response(request)
    response_payload = response.model_dump(mode="python")
    response_payload["parameters"]["kp"] = 1.3
    with pytest.raises(ValidationError, match="response hash"):
        HeboRunnerResponseV1.model_validate(response_payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_subprocess_transport_is_bounded_hash_bound_and_secret_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = build_hebo_runner_request(_observation(with_history=False))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-runner-boundary")
    runner_script = tmp_path / "fake_hebo_runner.py"
    runner_script.write_text(
        """
import hashlib
import json
import os
import sys

if "OPENAI_API_KEY" in os.environ:
    raise SystemExit(97)
request = json.loads(sys.stdin.buffer.read())
payload = {
    "schema_id": "dronedream.benchmark-hebo-runner-response/v1",
    "protocol_version": "hebo-isolated-json-stdio/v1",
    "adapter_id": "hebo/v1",
    "status": "proposed",
    "request_sha256": request["request_sha256"],
    "runner_environment_sha256": os.environ["DRONEDREAM_HEBO_RUNNER_ENV_SHA256"],
    "distribution_lock_sha256": request["distribution_lock_sha256"],
    "policy_sha256": request["policy_sha256"],
    "observed_feasible_count": len(request["feasible_history"]),
    "sobol_draws_consumed": request["sobol_draws_consumed"],
    "parameters": {item["name"]: item["baseline"] for item in request["parameter_domain"]},
}
canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
payload["response_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
""".lstrip(),
        encoding="utf-8",
    )
    python_path = Path(sys.executable).resolve()
    transport = JsonSubprocessHeboRunnerV1(
        python_executable=python_path,
        runner_script=runner_script.resolve(),
        expected_python_sha256=_sha256(python_path),
        expected_runner_script_sha256=_sha256(runner_script),
        runner_environment_sha256=ENVIRONMENT_SHA256,
        timeout_seconds=10,
    )

    response = transport.invoke(request)

    assert response.request_sha256 == request.request_sha256
    assert response.runner_environment_sha256 == ENVIRONMENT_SHA256
    assert response.parameters == {"kp": 1.0, "kd": 0.2, "mode": 1.0}

    runner_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    with pytest.raises(BenchmarkAdapterError, match="runner hash drifted"):
        transport.invoke(request)


def test_subprocess_transport_terminates_an_output_storm_at_the_cap(tmp_path: Path) -> None:
    request = build_hebo_runner_request(_observation(with_history=False))
    runner_script = tmp_path / "output_storm.py"
    runner_script.write_text(
        "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('x' * 1000000)\n",
        encoding="utf-8",
    )
    python_path = Path(sys.executable).resolve()
    transport = JsonSubprocessHeboRunnerV1(
        python_executable=python_path,
        runner_script=runner_script.resolve(),
        expected_python_sha256=_sha256(python_path),
        expected_runner_script_sha256=_sha256(runner_script),
        runner_environment_sha256=ENVIRONMENT_SHA256,
        timeout_seconds=10,
    )

    with pytest.raises(BenchmarkAdapterError, match="exceeds byte cap"):
        transport.invoke(request)


def test_subprocess_transport_enforces_timeout_when_runner_never_reads(tmp_path: Path) -> None:
    request = build_hebo_runner_request(_observation(with_history=False))
    runner_script = tmp_path / "stalled_runner.py"
    runner_script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    python_path = Path(sys.executable).resolve()
    transport = JsonSubprocessHeboRunnerV1(
        python_executable=python_path,
        runner_script=runner_script.resolve(),
        expected_python_sha256=_sha256(python_path),
        expected_runner_script_sha256=_sha256(runner_script),
        runner_environment_sha256=ENVIRONMENT_SHA256,
        timeout_seconds=0.1,
    )

    with pytest.raises(BenchmarkAdapterError, match="timed out"):
        transport.invoke(request)
