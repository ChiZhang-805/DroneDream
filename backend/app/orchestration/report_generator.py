"""JobReport generation and artifact registration.

The report generator turns aggregated candidate data persisted by
``app.orchestration.aggregation`` into a user-readable
:class:`~app.models.JobReport` row. Summary text is deterministic and local
to the worker/backend process; this module does not call an external LLM.

The module also registers job-level artifacts:

* mock backend metadata-only artifacts (comparison/trajectory/log/telemetry),
* real_cli concrete job artifact files + metadata rows, and
* backend-generated PDF report artifact rows.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.orchestration.events import record_event
from app.services.pdf_report import generate_job_pdf_report
from app.storage import get_artifact_storage

logger = logging.getLogger("drone_dream.orchestration.report_generator")

# --- Comparison point helpers ---------------------------------------------


def _comparison_points(
    baseline_agg: dict[str, Any], best_agg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build the baseline-vs-optimized comparison list used by the frontend."""

    def _point(
        key: str, label: str, unit: str | None, *, lower_is_better: bool
    ) -> dict[str, Any]:
        return {
            "metric": key,
            "label": label,
            "baseline": baseline_agg[key],
            "optimized": best_agg[key],
            "lower_is_better": lower_is_better,
            "unit": unit,
        }

    return [
        _point("rmse", "RMSE", "m", lower_is_better=True),
        _point("max_error", "Max error", "m", lower_is_better=True),
        _point("overshoot_count", "Overshoot", None, lower_is_better=True),
        _point("completion_time", "Completion time", "s", lower_is_better=True),
        _point("score", "Score", None, lower_is_better=True),
    ]


def _report_metrics(agg: dict[str, Any]) -> dict[str, Any]:
    """Narrow an aggregate dict to the :class:`AggregatedMetrics` schema shape."""

    return {
        "rmse": agg["rmse"],
        "max_error": agg["max_error"],
        "overshoot_count": agg["overshoot_count"],
        "completion_time": agg["completion_time"],
        "score": agg["score"],
    }


# --- Summary text ----------------------------------------------------------


def _pct_delta(baseline: float, optimized: float) -> float | None:
    """Return optimized-vs-baseline improvement as a percent (lower is better).

    Positive means "optimized is lower than baseline" (improvement on
    lower-is-better metrics). ``None`` when the baseline is zero and a
    percent is not meaningful.
    """

    if baseline == 0:
        return None
    return ((baseline - optimized) / baseline) * 100.0


def _pass_rate(trials: list[models.Trial]) -> float | None:
    """Return the pass_flag rate across this candidate's completed trials."""

    completed = [t for t in trials if t.status == "COMPLETED" and t.metric is not None]
    if not completed:
        return None
    passed = sum(1 for t in completed if t.metric is not None and t.metric.pass_flag)
    return passed / len(completed)


def _instability_rate(trials: list[models.Trial]) -> float:
    """Fraction of trials that finished with the instability flag set."""

    if not trials:
        return 0.0
    unstable = sum(
        1
        for t in trials
        if t.metric is not None and t.metric.instability_flag
    )
    return unstable / len(trials)


def generate_summary_text(
    *,
    best: models.CandidateParameterSet,
    baseline_agg: dict[str, Any],
    best_agg: dict[str, Any],
    baseline_trials: list[models.Trial],
    best_trials: list[models.Trial],
) -> str:
    """Produce a deterministic, local-only summary of the job's outcome.

    The text covers four beats required by the Phase 6 directive:

    1. Baseline performance (score + core error).
    2. Optimized performance (score + core error).
    3. Key improvement or tradeoff vs baseline.
    4. Any failure / instability notes the user should be aware of.
    """

    b_score = baseline_agg["aggregated_score"]
    o_score = best_agg["aggregated_score"]
    b_rmse = baseline_agg["rmse"]
    o_rmse = best_agg["rmse"]
    b_completion = baseline_agg["completion_time"]
    o_completion = best_agg["completion_time"]

    lines: list[str] = []

    # (1) Baseline
    lines.append(
        f"Baseline achieved aggregated score {b_score:.4f} "
        f"(RMSE {b_rmse:.3f} m, completion {b_completion:.2f} s) "
        f"over {len(baseline_trials)} trials."
    )

    # (2) Optimized — when the baseline wins, make that explicit.
    if best.is_baseline:
        lines.append(
            "No optimizer candidate beat the baseline on aggregated score; "
            "baseline parameters are therefore the recommended result."
        )
    else:
        lines.append(
            f"Optimizer candidate '{best.label}' (generation "
            f"{best.generation_index}) achieved aggregated score {o_score:.4f} "
            f"(RMSE {o_rmse:.3f} m, completion {o_completion:.2f} s) "
            f"over {len(best_trials)} trials."
        )

        # (3) Key improvement or tradeoff
        score_delta_pct = _pct_delta(b_score, o_score)
        rmse_delta_pct = _pct_delta(b_rmse, o_rmse)
        completion_delta_pct = _pct_delta(b_completion, o_completion)

        improvement_bits: list[str] = []
        if rmse_delta_pct is not None and rmse_delta_pct > 0.5:
            improvement_bits.append(f"{rmse_delta_pct:.1f}% lower tracking RMSE")
        if score_delta_pct is not None and score_delta_pct > 0.5:
            improvement_bits.append(f"{score_delta_pct:.1f}% lower aggregated score")

        tradeoff_bit: str | None = None
        if completion_delta_pct is not None and completion_delta_pct < -1.0:
            # Optimized is SLOWER than baseline.
            tradeoff_bit = (
                f"completion time increased by {-completion_delta_pct:.1f}% "
                f"(now {o_completion:.2f} s vs {b_completion:.2f} s baseline)"
            )

        if improvement_bits:
            lines.append(
                "Key improvement: "
                + ", ".join(improvement_bits)
                + "."
                + (f" Tradeoff: {tradeoff_bit}." if tradeoff_bit else "")
            )
        elif tradeoff_bit:
            lines.append(f"Tradeoff: {tradeoff_bit}.")

    # (4) Failure / instability notes
    best_failed = sum(1 for t in best_trials if t.status == "FAILED")
    best_instability = _instability_rate(best_trials)
    best_pass = _pass_rate(best_trials)

    notes: list[str] = []
    if best_failed > 0 and best_trials:
        notes.append(
            f"{best_failed} of {len(best_trials)} best-candidate trials failed"
        )
    if best_instability >= 0.25:
        notes.append(
            f"{best_instability * 100:.0f}% of best-candidate trials "
            f"flagged instability"
        )
    if best_pass is not None and best_pass < 0.75:
        notes.append(f"pass rate only {best_pass * 100:.0f}%")

    if notes:
        lines.append("Watch-outs: " + "; ".join(notes) + ".")
    else:
        lines.append(
            "No failure or instability flags on best-candidate trials."
        )

    return " ".join(lines)


# --- Report body ----------------------------------------------------------


def build_report_body(
    *,
    best: models.CandidateParameterSet,
    baseline_agg: dict[str, Any],
    best_agg: dict[str, Any],
    baseline_trials: list[models.Trial],
    best_trials: list[models.Trial],
) -> dict[str, Any]:
    """Compose the JobReport row payload (without persisting).

    Returns a dict with the five fields that map directly onto
    :class:`~app.models.JobReport` columns. Callers pass it to
    :func:`persist_report` to actually upsert the row.
    """

    return {
        "baseline_metric_json": _report_metrics(baseline_agg),
        "optimized_metric_json": _report_metrics(best_agg),
        "comparison_metric_json": _comparison_points(baseline_agg, best_agg),
        "best_parameter_json": dict(best.parameter_json or {}),
        "summary_text": generate_summary_text(
            best=best,
            baseline_agg=baseline_agg,
            best_agg=best_agg,
            baseline_trials=baseline_trials,
            best_trials=best_trials,
        ),
    }


def persist_report(
    db: Session,
    *,
    job: models.Job,
    best: models.CandidateParameterSet,
    report_body: dict[str, Any],
) -> models.JobReport:
    """Upsert the JobReport row for ``job`` and mark it READY."""

    existing = db.scalars(
        select(models.JobReport).where(models.JobReport.job_id == job.id)
    ).first()
    if existing is None:
        existing = models.JobReport(job_id=job.id)
        db.add(existing)
    existing.best_candidate_id = best.id
    existing.summary_text = report_body["summary_text"]
    existing.baseline_metric_json = report_body["baseline_metric_json"]
    existing.optimized_metric_json = report_body["optimized_metric_json"]
    existing.comparison_metric_json = report_body["comparison_metric_json"]
    existing.best_parameter_json = report_body["best_parameter_json"]
    existing.report_status = "READY"
    return existing


# --- Mock artifact metadata -----------------------------------------------


# Artifact types surfaced by `GET /api/v1/jobs/{job_id}/artifacts`. The MVP
# persists only metadata (no underlying files) — see docstring at the top of
# this module.
_JOB_ARTIFACT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "artifact_type": "comparison_plot",
        "display_name": "Baseline vs optimized comparison",
        "storage_path": "mock://jobs/{job_id}/comparison_plot.json",
        "mime_type": "application/json",
    },
    {
        "artifact_type": "trajectory_plot",
        "display_name": "Best-candidate trajectory",
        "storage_path": "mock://jobs/{job_id}/trajectory_plot.json",
        "mime_type": "application/json",
    },
    {
        "artifact_type": "worker_log",
        "display_name": "Worker execution log",
        "storage_path": "mock://jobs/{job_id}/worker.log",
        "mime_type": "text/plain",
    },
    {
        "artifact_type": "telemetry_json",
        "display_name": "Aggregate telemetry",
        "storage_path": "mock://jobs/{job_id}/telemetry.json",
        "mime_type": "application/json",
    },
)


def ensure_mock_job_artifacts(db: Session, job: models.Job) -> list[models.Artifact]:
    """Create the standard job-level artifact metadata rows if missing.

    Idempotent per ``(owner_id, artifact_type)`` — calling this twice for the
    same job does not create duplicate rows.
    """

    existing = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job.id)
    ).all()
    existing_keys = {(a.artifact_type, a.storage_path) for a in existing}

    created: list[models.Artifact] = []
    for template in _JOB_ARTIFACT_TEMPLATES:
        storage_path = template["storage_path"].format(job_id=job.id)
        if (template["artifact_type"], storage_path) in existing_keys:
            continue
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job.id,
            artifact_type=template["artifact_type"],
            display_name=template["display_name"],
            storage_path=storage_path,
            mime_type=template["mime_type"],
            file_size_bytes=None,
        )
        db.add(artifact)
        created.append(artifact)
    return created


def _real_artifact_root() -> Path:
    settings = get_settings()
    return Path(
        os.environ.get(
            "REAL_SIMULATOR_ARTIFACT_ROOT", str(settings.real_artifact_root_path)
        )
    ).resolve()


def _default_artifact_root() -> Path:
    return get_settings().default_artifact_root_path


def _write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")
    return len((text + "\n").encode("utf-8"))


def _write_text(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    path.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))


def _custom_track_summary(job: models.Job) -> tuple[int, list[dict[str, Any]]]:
    points = [p for p in (job.reference_track_json or []) if isinstance(p, dict)]
    return len(points), points[:5]


def ensure_real_job_artifacts(
    db: Session,
    *,
    job: models.Job,
    report_body: dict[str, Any],
    best: models.CandidateParameterSet,
) -> list[models.Artifact]:
    """Ensure real backend jobs expose concrete job-level artifact files + rows."""

    artifact_dir = _real_artifact_root() / "jobs" / job.id / "job_artifacts"
    custom_track_count, custom_track_preview = _custom_track_summary(job)
    report_payload = {
        "job_id": job.id,
        "best_candidate_id": best.id,
        "summary_text": report_body["summary_text"],
        "custom_track_point_count": custom_track_count,
        "custom_track_preview": custom_track_preview,
        "baseline_metrics": report_body["baseline_metric_json"],
        "optimized_metrics": report_body["optimized_metric_json"],
        "comparison": report_body["comparison_metric_json"],
        "best_parameters": report_body["best_parameter_json"],
    }
    candidate_summary = [
        {
            "candidate_id": c.id,
            "label": c.label,
            "is_baseline": c.is_baseline,
            "is_best": c.is_best,
            "source_type": c.source_type,
            "generation_index": c.generation_index,
            "aggregated_score": c.aggregated_score,
            "aggregated_metrics": c.aggregated_metric_json,
            "trial_count": c.trial_count,
            "completed_trial_count": c.completed_trial_count,
            "failed_trial_count": c.failed_trial_count,
            "rank_in_job": c.rank_in_job,
            "parameter_json": dict(c.parameter_json or {}),
        }
        for c in job.candidates
    ]
    trial_ids = [t.id for t in job.trials]
    trial_artifact_rows = (
        db.scalars(
            select(models.Artifact)
            .where(models.Artifact.owner_type == "trial")
            .where(models.Artifact.owner_id.in_(trial_ids))
        ).all()
        if trial_ids
        else []
    )
    trial_artifact_types: dict[str, set[str]] = {}
    for row in trial_artifact_rows:
        trial_artifact_types.setdefault(row.owner_id, set()).add(row.artifact_type)

    trial_summary = [
        {
            "trial_id": t.id,
            "candidate_id": t.candidate_id,
            "scenario": t.scenario_type,
            "seed": t.seed,
            "status": t.status,
            "pass": bool(t.metric.pass_flag) if t.metric is not None else None,
            "rmse": t.metric.rmse if t.metric is not None else None,
            "max_error": t.metric.max_error if t.metric is not None else None,
            "score": t.metric.score if t.metric is not None else None,
            "completion_time": t.metric.completion_time if t.metric is not None else None,
            "has_telemetry_json": "telemetry_json"
            in trial_artifact_types.get(t.id, set()),
            "has_reference_track_json": "reference_track_json"
            in trial_artifact_types.get(t.id, set()),
        }
        for t in job.trials
    ]
    if not trial_summary:
        trial_summary = [
            {
                "trial_id": None,
                "candidate_id": None,
                "scenario": None,
                "seed": None,
                "status": None,
                "pass": None,
                "rmse": None,
                "max_error": None,
                "score": None,
                "completion_time": None,
                "has_telemetry_json": False,
                "has_reference_track_json": False,
            }
        ]
    comparison_payload = {
        "job_id": job.id,
        "best_candidate_id": best.id,
        "baseline_metrics": report_body["baseline_metric_json"],
        "optimized_metrics": report_body["optimized_metric_json"],
        "comparison_points": report_body["comparison_metric_json"],
    }
    event_lines = [
        (
            f"{e.created_at.isoformat()} {e.event_type} "
            f"{json.dumps(e.payload_json or {}, sort_keys=True)}"
        )
        for e in sorted(job.events, key=lambda item: item.created_at)
    ]
    events_text = (
        "\n".join(event_lines)
        if event_lines
        else f"{job.created_at.isoformat()} job_created job_id={job.id}"
    )

    file_specs = [
        (
            "report_json",
            "Job report",
            "application/json",
            artifact_dir / "report.json",
            report_payload,
        ),
        (
            "candidate_summary_json",
            "Candidate summary",
            "application/json",
            artifact_dir / "candidate_summary.json",
            candidate_summary,
        ),
        (
            "trial_summary_json",
            "Trial summary",
            "application/json",
            artifact_dir / "trial_summary.json",
            trial_summary,
        ),
        (
            "comparison_json",
            "Comparison summary",
            "application/json",
            artifact_dir / "comparison.json",
            comparison_payload,
        ),
        (
            "job_events_log",
            "Job event log",
            "text/plain",
            artifact_dir / "job_events.log",
            events_text,
        ),
    ]

    existing = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job.id)
    ).all()
    existing_keys = {(a.artifact_type, a.storage_path) for a in existing}

    created: list[models.Artifact] = []
    storage = get_artifact_storage()
    for artifact_type, display_name, mime_type, path, payload in file_specs:
        size = (
            _write_text(path, payload)
            if isinstance(payload, str)
            else _write_json(path, payload)
        )
        storage_key = f"jobs/{job.id}/job_artifacts/{path.name}"
        storage_path = storage.put_file(str(path), storage_key, mime_type)
        if (artifact_type, storage_path) in existing_keys:
            continue
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job.id,
            artifact_type=artifact_type,
            display_name=display_name,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=size,
        )
        db.add(artifact)
        created.append(artifact)
    return created


def ensure_job_artifacts(
    db: Session,
    *,
    job: models.Job,
    report_body: dict[str, Any],
    best: models.CandidateParameterSet,
) -> list[models.Artifact]:
    if job.simulator_backend_requested == "real_cli":
        return ensure_real_job_artifacts(db, job=job, report_body=report_body, best=best)
    return ensure_mock_job_artifacts(db, job)


def _upsert_pdf_artifact(
    db: Session,
    *,
    job_id: str,
    pdf_path: Path,
    storage_path: str,
) -> models.Artifact:
    existing = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job_id)
        .where(models.Artifact.artifact_type == "pdf_report")
    ).first()
    if existing is None:
        existing = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            storage_path=storage_path,
        )
        db.add(existing)
    existing.display_name = f"{job_id} report.pdf"
    existing.storage_path = storage_path
    existing.mime_type = "application/pdf"
    existing.file_size_bytes = pdf_path.stat().st_size
    return existing


def ensure_job_pdf_artifact(db: Session, *, job: models.Job) -> models.Artifact:
    root = (
        _real_artifact_root()
        if job.simulator_backend_requested == "real_cli"
        else _default_artifact_root()
    )
    output_dir = root / "jobs" / job.id / "reports"
    pdf_path = generate_job_pdf_report(db=db, job=job, output_dir=output_dir)
    storage = get_artifact_storage()
    storage_path = storage.put_file(
        str(pdf_path), f"jobs/{job.id}/reports/{pdf_path.name}", "application/pdf"
    )
    return _upsert_pdf_artifact(db, job_id=job.id, pdf_path=pdf_path, storage_path=storage_path)


# --- Top-level entrypoint -------------------------------------------------


def generate_and_persist_report(
    db: Session,
    *,
    job: models.Job,
    best: models.CandidateParameterSet,
    baseline_agg: dict[str, Any],
    best_agg: dict[str, Any],
) -> models.JobReport:
    """Build the JobReport payload, persist it, and create mock artifacts.

    Called by :mod:`app.orchestration.aggregation` once the best candidate
    has been selected. Extracted to its own module so the summary/artifact
    logic is easy to reason about in isolation.
    """

    baseline_trials = [t for t in job.trials if t.candidate_id == (job.baseline_candidate_id or "")]
    best_trials = [t for t in job.trials if t.candidate_id == best.id]

    body = build_report_body(
        best=best,
        baseline_agg=baseline_agg,
        best_agg=best_agg,
        baseline_trials=baseline_trials,
        best_trials=best_trials,
    )
    custom_track_count, _ = _custom_track_summary(job)
    if custom_track_count:
        body["summary_text"] = (
            f"{body['summary_text']} Custom track points: {custom_track_count} "
            "(preview limited to first 5 points in artifacts/PDF)."
        )
    report = persist_report(db, job=job, best=best, report_body=body)
    ensure_job_artifacts(db, job=job, report_body=body, best=best)
    try:
        ensure_job_pdf_artifact(db, job=job)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("pdf report generation failed for job %s", job.id)
        record_event(
            db,
            job.id,
            "pdf_report_generation_failed",
            {"error": str(exc)},
        )
    return report


__all__ = [
    "build_report_body",
    "ensure_job_artifacts",
    "ensure_mock_job_artifacts",
    "ensure_real_job_artifacts",
    "ensure_job_pdf_artifact",
    "generate_and_persist_report",
    "generate_summary_text",
    "persist_report",
]
