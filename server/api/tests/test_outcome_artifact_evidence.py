from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.db import Base
from app.optimization.outcome_contract import build_selection_key
from app.optimization.outcome_evidence import (
    CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA,
    CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA,
    CandidateOutcomeEvidenceV2,
    CandidateReportEvidenceError,
    CandidateReportEvidenceV2,
    candidate_report_trial_evidence_rows,
    candidate_training_trial_evidence_rows,
    compile_candidate_outcome_evidence,
    compile_candidate_report_evidence,
    require_authoritative_candidate_report_projection,
    verify_candidate_outcome_evidence,
    verify_candidate_report_evidence,
)
from app.storage.evidence import (
    MOCK_METADATA_ARTIFACT_EVIDENCE,
    SEALED_ARTIFACT_EVIDENCE,
    candidate_trial_artifact_evidence,
)
from app.storage.integrity import (
    ArtifactIntegrityError,
    bind_artifact_integrity,
)


def _aggregate() -> dict[str, object]:
    return {
        "training_trial_count": 1,
        "training_completed_trial_count": 1,
        "training_failed_trial_count": 0,
        "training_passing_trial_count": 1,
        "training_trial_outcome_counts": {
            "success": 1,
            "domain_failure": 0,
            "infrastructure_failure": 0,
            "cancelled": 0,
            "invalid_evidence": 0,
            "unknown_failure": 0,
        },
        "training_trial_outcome_rates": {
            "success": 1.0,
            "domain_failure": 0.0,
            "infrastructure_failure": 0.0,
            "cancelled": 0.0,
            "invalid_evidence": 0.0,
            "unknown_failure": 0.0,
        },
        "optimizer_learning_failure_rate": 0.0,
        "objective_values": {"rmse": 0.4},
        "constraint_values": {"crash_flag:lte:0": 0.0},
        "constraint_violations": {"crash_flag:lte:0": 0.0},
        "feasible": True,
        "preference_loss": 0.4,
        "soft_constraint_penalty": 0.0,
        "scalar_loss": 0.4,
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0.0,
            training_failure_rate=0.0,
            decision_loss=0.4,
        ),
        "acceptance_rmse": 0.4,
        "acceptance_max_error": 0.8,
        "acceptance_pass_rate": 1.0,
        "acceptance_completion_rate": 1.0,
        "rmse": 0.4,
        "max_error": 0.8,
        "max_error_mean": 0.6,
        "max_error_worst": 0.8,
        "overshoot_count": 0,
        "completion_time": 3.0,
        "score": 0.4,
        "aggregated_score": 0.4,
        "completion_rate": 1.0,
        "failure_rate": 0.0,
        "pass_rate": 1.0,
        "holdout": {
            "validation_status": "passed",
            "feasible": True,
        },
    }


def _trial(
    *,
    trial_id: str,
    candidate_id: str,
    job_id: str,
    holdout: bool,
    seed: int,
) -> models.Trial:
    trial = models.Trial(
        id=trial_id,
        candidate_id=candidate_id,
        job_id=job_id,
        seed=seed,
        scenario_type="nominal",
        scenario_config_json={"holdout": holdout},
        status="COMPLETED",
    )
    trial.metric = models.TrialMetric(
        id=f"metric-{trial_id}",
        trial_id=trial_id,
        rmse=0.4,
        max_error=0.8,
        overshoot_count=0,
        completion_time=3.0,
        crash_flag=False,
        timeout_flag=False,
        score=0.4,
        final_error=0.1,
        pass_flag=True,
        instability_flag=False,
    )
    return trial


def test_candidate_v2_binds_verified_trial_artifact_bytes_and_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "local")
    get_settings.cache_clear()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as db:
        job = models.Job(
            id="job-artifact-evidence",
            track_type="circle",
            altitude_m=10.0,
            sensor_noise_level="low",
            objective_profile="balanced",
        )
        candidate = models.CandidateParameterSet(
            id="candidate-artifact-evidence",
            job_id=job.id,
            generation_index=2,
            parameter_json={"MPC_XY_P": 0.95},
        )
        unrelated_candidate = models.CandidateParameterSet(
            id="candidate-unrelated",
            job_id=job.id,
            generation_index=2,
            parameter_json={"MPC_XY_P": 1.05},
        )
        training = _trial(
            trial_id="trial-training",
            candidate_id=candidate.id,
            job_id=job.id,
            holdout=False,
            seed=101,
        )
        holdout = _trial(
            trial_id="trial-holdout",
            candidate_id=candidate.id,
            job_id=job.id,
            holdout=True,
            seed=201,
        )
        unrelated = _trial(
            trial_id="trial-unrelated",
            candidate_id=unrelated_candidate.id,
            job_id=job.id,
            holdout=False,
            seed=301,
        )
        candidate.trials = [training, holdout]
        unrelated_candidate.trials = [unrelated]
        job.candidates = [candidate, unrelated_candidate]
        job.trials = [training, holdout, unrelated]
        db.add(job)
        db.flush()

        training_path = tmp_path / "training-telemetry.json"
        training_path.write_bytes(b'{"trial":"training"}\n')
        training_artifact = models.Artifact(
            id="artifact-training",
            owner_type="trial",
            owner_id=training.id,
            artifact_type="telemetry_json",
            display_name="Training telemetry",
            storage_path=str(training_path),
            mime_type="application/json",
        )
        holdout_path = tmp_path / "holdout-telemetry.json"
        holdout_path.write_bytes(b'{"trial":"holdout"}\n')
        holdout_artifact = models.Artifact(
            id="artifact-holdout",
            owner_type="trial",
            owner_id=holdout.id,
            artifact_type="telemetry_json",
            display_name="Holdout telemetry",
            storage_path=str(holdout_path),
            mime_type="application/json",
        )
        unrelated_path = tmp_path / "unrelated.json"
        unrelated_path.write_bytes(b'{"trial":"unrelated"}\n')
        unrelated_artifact = models.Artifact(
            id="artifact-unrelated",
            owner_type="trial",
            owner_id=unrelated.id,
            artifact_type="telemetry_json",
            storage_path=str(unrelated_path),
            mime_type="application/json",
        )
        mock_artifact = models.Artifact(
            id="artifact-mock",
            owner_type="trial",
            owner_id=training.id,
            artifact_type="trajectory_plot",
            storage_path="mock://trials/trial-training/trajectory.png",
            mime_type="image/png",
        )
        db.add_all(
            [
                training_artifact,
                holdout_artifact,
                unrelated_artifact,
                mock_artifact,
            ]
        )
        for artifact, path in (
            (training_artifact, training_path),
            (holdout_artifact, holdout_path),
            (unrelated_artifact, unrelated_path),
        ):
            bind_artifact_integrity(db, artifact=artifact, content=path)
        db.commit()

        report_rows = candidate_report_trial_evidence_rows(
            candidate,
            bind_artifacts=True,
            verify_artifact_bytes=True,
        )
        training_rows = candidate_training_trial_evidence_rows(
            candidate,
            bind_artifacts=True,
            verify_artifact_bytes=True,
        )
        assert report_rows is not None
        assert training_rows is not None
        assert len(report_rows) == 2
        assert len(training_rows) == 1
        training_artifacts = training_rows[0]["artifact_evidence"]
        assert training_artifacts["artifact_count"] == 2
        assert {
            row["content_evidence"]
            for row in training_artifacts["artifacts"]
        } == {
            SEALED_ARTIFACT_EVIDENCE,
            MOCK_METADATA_ARTIFACT_EVIDENCE,
        }
        assert all(
            row["artifact_id"] != unrelated_artifact.id
            for trial_row in report_rows
            for row in trial_row["artifact_evidence"]["artifacts"]
        )

        aggregate = _aggregate()
        outcome = compile_candidate_outcome_evidence(
            outcome_contract_id="sha256:" + "a" * 64,
            candidate_id=candidate.id,
            generation_index=candidate.generation_index,
            parameter_snapshot=candidate.parameter_json,
            trial_evidence_rows=training_rows,
            aggregate=aggregate,
            bind_trial_artifacts=True,
        )
        assert isinstance(outcome, CandidateOutcomeEvidenceV2)
        assert outcome.schema_id == CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA
        assert outcome.artifact_count == 2
        assert outcome.sealed_artifact_count == 1
        assert outcome.metadata_only_artifact_count == 1
        assert (
            compile_candidate_outcome_evidence(
                outcome_contract_id="sha256:" + "a" * 64,
                candidate_id=candidate.id,
                generation_index=candidate.generation_index,
                parameter_snapshot=candidate.parameter_json,
                trial_evidence_rows=training_rows,
                aggregate=aggregate,
                bind_trial_artifacts=True,
            )
            == outcome
        )

        report = compile_candidate_report_evidence(
            candidate_outcome_evidence=outcome.model_dump(mode="json"),
            report_trial_evidence_rows=report_rows,
            aggregate=aggregate,
        )
        assert isinstance(report, CandidateReportEvidenceV2)
        assert report.schema_id == CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA
        assert report.artifact_count == 3
        assert report.sealed_artifact_count == 2
        assert report.metadata_only_artifact_count == 1
        assert verify_candidate_outcome_evidence(
            outcome.model_dump(mode="json")
        ) == outcome
        assert verify_candidate_report_evidence(
            report.model_dump(mode="json")
        ) == report

        candidate.aggregated_metric_json = {
            **aggregate,
            "candidate_outcome_evidence_required": True,
            "candidate_outcome_evidence": outcome.model_dump(mode="json"),
            "candidate_report_evidence_required": True,
            "candidate_report_evidence": report.model_dump(mode="json"),
        }
        assert candidate.evidence_ledger_required is False
        projection = require_authoritative_candidate_report_projection(
            candidate,
            verify_artifact_bytes=True,
        )
        assert projection["sealed_artifact_count"] == 2
        assert projection["metadata_only_artifact_count"] == 1

        training_path.write_bytes(b'{"trial":"tampered"}\n')
        with pytest.raises(
            CandidateReportEvidenceError,
            match="does not match current",
        ):
            require_authoritative_candidate_report_projection(
                candidate,
                verify_artifact_bytes=True,
            )

    get_settings.cache_clear()


def test_real_trial_artifact_without_receipt_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "local")
    get_settings.cache_clear()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as db:
        job = models.Job(
            id="job-unsealed",
            track_type="circle",
            altitude_m=10.0,
            sensor_noise_level="low",
            objective_profile="balanced",
        )
        candidate = models.CandidateParameterSet(
            id="candidate-unsealed",
            job_id=job.id,
            parameter_json={"MPC_XY_P": 0.95},
        )
        trial = _trial(
            trial_id="trial-unsealed",
            candidate_id=candidate.id,
            job_id=job.id,
            holdout=False,
            seed=101,
        )
        candidate.trials = [trial]
        job.candidates = [candidate]
        job.trials = [trial]
        path = tmp_path / "unsealed.json"
        path.write_bytes(b"{}\n")
        db.add(job)
        db.add(
            models.Artifact(
                id="artifact-unsealed",
                owner_type="trial",
                owner_id=trial.id,
                artifact_type="telemetry_json",
                storage_path=str(path),
                mime_type="application/json",
            )
        )
        db.commit()

        with pytest.raises(
            ArtifactIntegrityError,
            match="missing a sealed byte receipt",
        ):
            candidate_trial_artifact_evidence(
                candidate,
                [trial],
                verify_bytes=True,
            )
        assert (
            candidate_training_trial_evidence_rows(
                candidate,
                bind_artifacts=True,
                verify_artifact_bytes=True,
            )
            is None
        )

    get_settings.cache_clear()
