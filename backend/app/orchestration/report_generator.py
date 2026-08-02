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

import contextlib
import json
import logging
import math
import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.optimization.outcome_evidence import (
    CandidateReportEvidenceError,
    authoritative_candidate_trial_outcome_projection,
    candidate_report_evidence_required,
    candidate_training_trial_evidence_rows,
    require_authoritative_candidate_report_projection,
    trial_is_holdout,
)
from app.optimization.winner_evidence import (
    WinnerSelectionEvidenceV1,
    verify_winner_selection_evidence,
    winner_evidence_matches_current_candidates,
)
from app.orchestration.events import record_event
from app.orchestration.repro_manifest import build_repro_manifest, sanitize_payload
from app.orchestration.winner_freeze import (
    WinnerFreezeError,
    freeze_winner_selection,
    require_winner_freeze_receipt,
)
from app.services.pdf_report import render_job_pdf_report
from app.storage import get_artifact_storage
from app.storage.integrity import (
    ArtifactIntegrityError,
    artifact_content_digest,
    bind_artifact_integrity,
    require_artifact_integrity,
)
from app.storage.registration import guard_artifact_registration
from app.time_utils import canonical_utc_iso

logger = logging.getLogger("drone_dream.orchestration.report_generator")


class ReportEvidenceError(RuntimeError):
    """Raised when a required bound report projection does not verify."""


def _authoritative_report_aggregate(
    candidate: models.CandidateParameterSet,
    aggregate: object,
    *,
    verify_artifact_bytes: bool = False,
) -> dict[str, Any]:
    try:
        projection = require_authoritative_candidate_report_projection(
            candidate,
            aggregate,
            verify_artifact_bytes=verify_artifact_bytes,
        )
    except CandidateReportEvidenceError as exc:
        raise ReportEvidenceError(str(exc)) from exc
    if not projection:
        raise ReportEvidenceError("Candidate report aggregate is missing")
    return projection


# --- Comparison point helpers ---------------------------------------------


def _comparison_points(
    baseline_agg: dict[str, Any], best_agg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build the baseline-vs-optimized comparison list used by the frontend."""

    def _point(
        key: str,
        label: str,
        unit: str | None,
        *,
        lower_is_better: bool,
        source_key: str | None = None,
    ) -> dict[str, Any]:
        value_key = source_key or key
        return {
            "metric": key,
            "label": label,
            "baseline": baseline_agg.get(value_key),
            "optimized": best_agg.get(value_key),
            "lower_is_better": lower_is_better,
            "unit": unit,
        }

    return [
        _point("rmse", "RMSE", "m", lower_is_better=True),
        _point(
            "max_error_worst",
            "Worst max error",
            "m",
            lower_is_better=True,
            source_key="max_error_worst",
        ),
        _point("overshoot_count", "Overshoot", None, lower_is_better=True),
        _point("completion_time", "Completion time", "s", lower_is_better=True),
        _point("score", "Score", None, lower_is_better=True),
    ]


def _report_metrics(agg: dict[str, Any]) -> dict[str, Any]:
    """Narrow an aggregate dict to the :class:`AggregatedMetrics` schema shape."""

    result: dict[str, Any] = {
        "rmse": agg["rmse"],
        "max_error": agg["max_error"],
        "max_error_mean": agg.get("max_error_mean", agg["max_error"]),
        "max_error_worst": agg.get("max_error_worst", agg["max_error"]),
        "overshoot_count": agg["overshoot_count"],
        "completion_time": agg["completion_time"],
        "score": agg["score"],
    }
    for key in ("completion_rate", "failure_rate", "pass_rate", "holdout"):
        if key in agg:
            result[key] = agg[key]
    return result


# --- Summary text ----------------------------------------------------------


def _summary_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _format_summary_number(
    value: object,
    *,
    decimals: int,
    unit: str = "",
) -> str:
    number = _summary_number(value)
    if number is None:
        return "unavailable"
    return f"{number:.{decimals}f}{unit}"


def _pct_delta(baseline: object, optimized: object) -> float | None:
    """Return optimized-vs-baseline improvement as a percent (lower is better).

    Positive means "optimized is lower than baseline" (improvement on
    lower-is-better metrics). ``None`` when the baseline is zero and a
    percent is not meaningful.
    """

    baseline_number = _summary_number(baseline)
    optimized_number = _summary_number(optimized)
    if baseline_number is None or optimized_number is None or baseline_number == 0:
        return None
    return ((baseline_number - optimized_number) / baseline_number) * 100.0


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
        "Baseline achieved aggregated score "
        f"{_format_summary_number(b_score, decimals=4)} "
        f"(RMSE {_format_summary_number(b_rmse, decimals=3, unit=' m')}, "
        "completion "
        f"{_format_summary_number(b_completion, decimals=2, unit=' s')}) "
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
            f"{best.generation_index}) achieved aggregated score "
            f"{_format_summary_number(o_score, decimals=4)} "
            f"(RMSE {_format_summary_number(o_rmse, decimals=3, unit=' m')}, "
            "completion "
            f"{_format_summary_number(o_completion, decimals=2, unit=' s')}) "
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
                "(now "
                f"{_format_summary_number(o_completion, decimals=2, unit=' s')} "
                "vs "
                f"{_format_summary_number(b_completion, decimals=2, unit=' s')} "
                "baseline)"
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
    if not best_trials:
        notes.append("no best-candidate trial rows were available")
    elif best_failed > 0:
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
    winner_evidence: dict[str, Any] | None = None,
    winner_freeze_receipt: models.WinnerFreezeReceipt | None = None,
) -> models.JobReport:
    """Upsert the JobReport row for ``job`` and mark it READY."""

    existing = db.scalars(
        select(models.JobReport).where(models.JobReport.job_id == job.id)
    ).first()
    if existing is None:
        existing = models.JobReport(job_id=job.id)
        db.add(existing)
    existing.job = job
    existing.best_candidate_id = best.id
    existing.summary_text = report_body["summary_text"]
    existing.baseline_metric_json = report_body["baseline_metric_json"]
    existing.optimized_metric_json = report_body["optimized_metric_json"]
    existing.comparison_metric_json = report_body["comparison_metric_json"]
    existing.best_parameter_json = report_body["best_parameter_json"]
    existing.winner_evidence_json = winner_evidence
    existing.winner_freeze_receipt = winner_freeze_receipt
    existing.winner_freeze_receipt_id = (
        winner_freeze_receipt.id
        if winner_freeze_receipt is not None
        else None
    )
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

    guard_artifact_registration(db, owner_type="job", owner_id=job.id)
    existing = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job.id)
    ).all()
    existing_types = {artifact.artifact_type for artifact in existing}

    created: list[models.Artifact] = []
    for template in _JOB_ARTIFACT_TEMPLATES:
        storage_path = template["storage_path"].format(job_id=job.id)
        if template["artifact_type"] in existing_types:
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


def _json_bytes(payload: Any) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _text_bytes(text: str) -> bytes:
    body = text if text.endswith("\n") else text + "\n"
    return body.encode("utf-8")


def _require_existing_artifact_bytes(path: Path, content: bytes) -> None:
    try:
        expected = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(expected.st_mode):
        raise ArtifactIntegrityError(
            "immutable artifact destination is not a regular file"
        )
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise ArtifactIntegrityError(
                "immutable artifact destination changed while opening"
            )
        stored = stream.read(len(content) + 1)
        finished = os.fstat(stream.fileno())
    if (
        (finished.st_dev, finished.st_ino) != (opened.st_dev, opened.st_ino)
        or finished.st_size != opened.st_size
        or finished.st_mtime_ns != opened.st_mtime_ns
    ):
        raise ArtifactIntegrityError(
            "immutable artifact destination changed while reading"
        )
    if stored != content:
        raise ArtifactIntegrityError(
            "unregistered immutable artifact bytes differ from regeneration"
        )


def _publish_immutable_artifact(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = path.parent.resolve()
    if not any(
        resolved_parent.is_relative_to(root)
        for root in get_settings().allowed_artifact_roots
    ):
        raise ArtifactIntegrityError(
            "immutable artifact destination is outside allowed roots"
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        _require_existing_artifact_bytes(path, content)
        return
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        with contextlib.suppress(OSError):
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _ensure_immutable_file_artifact(
    db: Session,
    *,
    existing: models.Artifact | None,
    owner_type: str,
    owner_id: str,
    artifact_type: str,
    display_name: str,
    mime_type: str,
    path: Path,
    storage_key: str,
    content: bytes,
) -> tuple[models.Artifact, bool]:
    """Create a sealed artifact or prove an existing artifact is an exact retry.

    Existing storage is verified before generated bytes are compared.  No file
    or object is written on the retry path, so a failed regeneration cannot
    destroy the last verified copy.
    """

    storage = get_artifact_storage()
    if existing is not None:
        if (
            existing.owner_type != owner_type
            or existing.owner_id != owner_id
            or existing.artifact_type != artifact_type
        ):
            raise ArtifactIntegrityError(
                "existing artifact identity does not match requested artifact"
            )
        stored_digest = storage.content_digest(existing.storage_path)
        receipt = require_artifact_integrity(existing, content_digest=stored_digest)
        if receipt is None and stored_digest != artifact_content_digest(content):
            raise ArtifactIntegrityError(
                "legacy artifact bytes differ from deterministic regeneration"
            )
        # For a bound artifact, this accepts only the exact content digest.
        # For an exact legacy artifact, it creates the first immutable receipt.
        existing.display_name = display_name
        existing.mime_type = mime_type
        bind_artifact_integrity(db, artifact=existing, content=content)
        return existing, False

    _publish_immutable_artifact(path, content)
    storage_path = storage.put_file(path, storage_key, mime_type)
    stored_digest = storage.content_digest(storage_path)
    if stored_digest != artifact_content_digest(content):
        raise ArtifactIntegrityError(
            "artifact storage did not preserve the generated bytes"
        )
    artifact = models.Artifact(
        owner_type=owner_type,
        owner_id=owner_id,
        artifact_type=artifact_type,
        display_name=display_name,
        storage_path=storage_path,
        mime_type=mime_type,
    )
    db.add(artifact)
    bind_artifact_integrity(db, artifact=artifact, content=content)
    return artifact, True


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

    guard_artifact_registration(db, owner_type="job", owner_id=job.id)
    artifact_dir = _real_artifact_root() / "jobs" / job.id / "job_artifacts"
    custom_track_count, custom_track_preview = _custom_track_summary(job)
    winner_freeze = job.winner_freeze
    verified_winner = (
        require_winner_freeze_receipt(
            winner_freeze,
            job=job,
            evidence=(
                job.report.winner_evidence_json
                if job.report is not None
                else None
            ),
        )
        if winner_freeze is not None
        else None
    )
    report_payload = {
        "job_id": job.id,
        "best_candidate_id": best.id,
        "winner_selection_evidence": sanitize_payload(
            verified_winner.model_dump(mode="json")
            if verified_winner is not None
            else None
        ),
        "winner_freeze_receipt": sanitize_payload(
            {
                "receipt_id": winner_freeze.id,
                "receipt_schema": winner_freeze.receipt_schema,
                "evidence_id": winner_freeze.evidence_id,
                "frozen_at": canonical_utc_iso(winner_freeze.frozen_at),
            }
            if verified_winner is not None
            and winner_freeze is not None
            else None
        ),
        "summary_text": report_body["summary_text"],
        "custom_track_point_count": custom_track_count,
        "custom_track_preview": sanitize_payload(custom_track_preview),
        "baseline_metrics": report_body["baseline_metric_json"],
        "optimized_metrics": report_body["optimized_metric_json"],
        "comparison": report_body["comparison_metric_json"],
        "best_parameters": report_body["best_parameter_json"],
    }
    candidate_summary: list[dict[str, Any]] = []
    for candidate in sorted(
        job.candidates,
        key=lambda item: (
            item.generation_index,
            canonical_utc_iso(item.created_at) or "",
            item.id,
        ),
    ):
        aggregate = (
            _authoritative_report_aggregate(
                candidate,
                candidate.aggregated_metric_json,
            )
            if candidate.aggregated_metric_json is not None
            else {}
        )
        candidate_trials = list(candidate.trials)
        candidate_summary.append(
            {
                "candidate_id": candidate.id,
                "label": candidate.label,
                "is_baseline": candidate.is_baseline,
                "is_best": candidate.is_best,
                "source_type": candidate.source_type,
                "generation_index": candidate.generation_index,
                "aggregated_score": aggregate.get("aggregated_score"),
                "aggregated_metrics": sanitize_payload(aggregate),
                "trial_count": len(candidate_trials),
                "completed_trial_count": sum(
                    trial.status == "COMPLETED"
                    for trial in candidate_trials
                ),
                "failed_trial_count": sum(
                    trial.status == "FAILED" for trial in candidate_trials
                ),
                "rank_in_job": candidate.rank_in_job,
                "parameter_json": sanitize_payload(
                    dict(candidate.parameter_json or {})
                ),
            }
        )
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
        for t in sorted(
            job.trials,
            key=lambda item: (
                item.candidate_id,
                item.scenario_type,
                item.seed,
                item.id,
            ),
        )
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
            f"{canonical_utc_iso(e.created_at)} {e.event_type} "
            f"{json.dumps(sanitize_payload(e.payload_json or {}), sort_keys=True, allow_nan=False)}"
        )
        for e in sorted(
            job.events,
            key=lambda item: (
                canonical_utc_iso(item.created_at) or "",
                item.id,
            ),
        )
    ]
    events_text = (
        "\n".join(event_lines)
        if event_lines
        else f"{canonical_utc_iso(job.created_at)} job_created job_id={job.id}"
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
    existing_by_type: dict[str, models.Artifact] = {}
    for artifact in existing:
        if artifact.artifact_type in existing_by_type:
            raise ArtifactIntegrityError(
                "job contains multiple artifacts for an immutable artifact type"
            )
        existing_by_type[artifact.artifact_type] = artifact

    created: list[models.Artifact] = []
    for artifact_type, display_name, mime_type, path, payload in file_specs:
        content = (
            _text_bytes(payload)
            if isinstance(payload, str)
            else _json_bytes(payload)
        )
        storage_key = f"jobs/{job.id}/job_artifacts/{path.name}"
        artifact, was_created = _ensure_immutable_file_artifact(
            db,
            existing=existing_by_type.get(artifact_type),
            owner_type="job",
            owner_id=job.id,
            artifact_type=artifact_type,
            display_name=display_name,
            mime_type=mime_type,
            path=path,
            storage_key=storage_key,
            content=content,
        )
        if was_created:
            created.append(artifact)
            existing_by_type[artifact_type] = artifact
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




def ensure_repro_manifest_artifact(
    db: Session,
    *,
    job: models.Job,
    best: models.CandidateParameterSet,
) -> models.Artifact:
    guard_artifact_registration(db, owner_type="job", owner_id=job.id)
    root = (
        _real_artifact_root()
        if job.simulator_backend_requested == "real_cli"
        else _default_artifact_root()
    )
    manifest_path = root / "jobs" / job.id / "job_artifacts" / "repro_manifest.json"
    manifest_payload = build_repro_manifest(job=job, best=best)
    existing_rows = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job.id)
        .where(models.Artifact.artifact_type == "repro_manifest_json")
    ).all()
    if len(existing_rows) > 1:
        raise ArtifactIntegrityError(
            "job contains multiple reproducibility manifest artifacts"
        )
    artifact, _ = _ensure_immutable_file_artifact(
        db,
        existing=existing_rows[0] if existing_rows else None,
        owner_type="job",
        owner_id=job.id,
        artifact_type="repro_manifest_json",
        display_name="Reproducibility manifest",
        mime_type="application/json",
        path=manifest_path,
        storage_key=f"jobs/{job.id}/job_artifacts/{manifest_path.name}",
        content=_json_bytes(manifest_payload),
    )
    return artifact


def ensure_job_pdf_artifact(db: Session, *, job: models.Job) -> models.Artifact:
    guard_artifact_registration(db, owner_type="job", owner_id=job.id)
    root = (
        _real_artifact_root()
        if job.simulator_backend_requested == "real_cli"
        else _default_artifact_root()
    )
    output_dir = root / "jobs" / job.id / "reports"
    pdf_path = (output_dir / f"{job.id} report.pdf").resolve()
    existing_rows = db.scalars(
        select(models.Artifact)
        .where(models.Artifact.owner_type == "job")
        .where(models.Artifact.owner_id == job.id)
        .where(models.Artifact.artifact_type == "pdf_report")
    ).all()
    if len(existing_rows) > 1:
        raise ArtifactIntegrityError("job contains multiple PDF report artifacts")
    artifact, _ = _ensure_immutable_file_artifact(
        db,
        existing=existing_rows[0] if existing_rows else None,
        owner_type="job",
        owner_id=job.id,
        artifact_type="pdf_report",
        display_name=f"{job.id} report.pdf",
        mime_type="application/pdf",
        path=pdf_path,
        storage_key=f"jobs/{job.id}/reports/{pdf_path.name}",
        content=render_job_pdf_report(job),
    )
    return artifact


# --- Top-level entrypoint -------------------------------------------------


def generate_and_persist_report(
    db: Session,
    *,
    job: models.Job,
    best: models.CandidateParameterSet,
    baseline_agg: dict[str, Any],
    best_agg: dict[str, Any],
    winner_evidence: WinnerSelectionEvidenceV1 | dict[str, Any] | None = None,
) -> models.JobReport:
    """Build the JobReport payload, persist it, and create mock artifacts.

    Called by :mod:`app.orchestration.aggregation` once the best candidate
    has been selected. Extracted to its own module so the summary/artifact
    logic is easy to reason about in isolation.
    """

    baseline = next(
        (
            candidate
            for candidate in job.candidates
            if candidate.id == (job.baseline_candidate_id or "")
        ),
        None,
    )
    if baseline is None:
        raise ReportEvidenceError("baseline Candidate is missing")
    aggregated_candidates = [
        candidate
        for candidate in job.candidates
        if candidate.aggregated_metric_json is not None
    ]
    verified_aggregates = {
        candidate.id: _authoritative_report_aggregate(
            candidate,
            candidate.aggregated_metric_json,
            verify_artifact_bytes=True,
        )
        for candidate in aggregated_candidates
    }
    outcome_projections: dict[str, dict[str, Any]] = {}
    for candidate in aggregated_candidates:
        projection = authoritative_candidate_trial_outcome_projection(
            candidate_id=candidate.id,
            generation_index=candidate.generation_index,
            parameter_snapshot=candidate.parameter_json,
            trial_evidence_rows=candidate_training_trial_evidence_rows(
                candidate
            ),
            aggregate=candidate.aggregated_metric_json,
        )
        if (
            candidate_report_evidence_required(
                candidate.aggregated_metric_json
            )
            and not projection
        ):
            raise ReportEvidenceError(
                "Candidate outcome evidence is invalid at report boundary"
            )
        outcome_projections[candidate.id] = projection
    winner_payload = (
        winner_evidence.model_dump(mode="json")
        if isinstance(winner_evidence, WinnerSelectionEvidenceV1)
        else winner_evidence
    )
    verified_winner = verify_winner_selection_evidence(winner_payload)
    winner_required = (
        job.best_candidate_id is not None
        and any(
            candidate_report_evidence_required(
                candidate.aggregated_metric_json
            )
            for candidate in aggregated_candidates
        )
    )
    if winner_payload is not None and verified_winner is None:
        raise ReportEvidenceError(
            "winner-selection evidence content hash is invalid"
        )
    if winner_required and verified_winner is None:
        raise ReportEvidenceError(
            "winner-selection evidence is required for this report"
        )
    if verified_winner is not None and (
        verified_winner.winner_candidate_id != best.id
        or verified_winner.winner_candidate_id != job.best_candidate_id
        or verified_winner.baseline_candidate_id
        != job.baseline_candidate_id
        or any(
            projection.get("outcome_contract_id")
            != verified_winner.outcome_contract_id
            for projection in outcome_projections.values()
        )
        or not winner_evidence_matches_current_candidates(
            verified_winner.model_dump(mode="json"),
            candidates=aggregated_candidates,
            outcome_projections=outcome_projections,
            report_projections=verified_aggregates,
        )
    ):
        raise ReportEvidenceError(
            "winner-selection evidence no longer matches current ranking"
        )
    baseline_agg = verified_aggregates.get(
        baseline.id
    ) or _authoritative_report_aggregate(baseline, baseline_agg)
    best_agg = verified_aggregates.get(
        best.id
    ) or _authoritative_report_aggregate(best, best_agg)
    try:
        baseline_trials = [
            t
            for t in job.trials
            if t.candidate_id == (job.baseline_candidate_id or "")
            and not trial_is_holdout(t)
        ]
        best_trials = [
            t
            for t in job.trials
            if t.candidate_id == best.id and not trial_is_holdout(t)
        ]
    except ValueError as exc:
        raise ReportEvidenceError(
            "Candidate Trial role is malformed; refusing to publish a report"
        ) from exc

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
    winner_freeze_receipt = None
    if verified_winner is not None:
        try:
            winner_freeze_receipt = freeze_winner_selection(
                db,
                job=job,
                evidence=verified_winner,
            )
        except WinnerFreezeError as exc:
            raise ReportEvidenceError(str(exc)) from exc
    report = persist_report(
        db,
        job=job,
        best=best,
        report_body=body,
        winner_evidence=(
            verified_winner.model_dump(mode="json")
            if verified_winner is not None
            else None
        ),
        winner_freeze_receipt=winner_freeze_receipt,
    )
    ensure_job_artifacts(db, job=job, report_body=body, best=best)
    try:
        ensure_repro_manifest_artifact(db, job=job, best=best)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("repro manifest generation failed for job %s", job.id)
        record_event(
            db,
            job.id,
            "repro_manifest_generation_failed",
            {"error": str(exc)},
        )
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
    "ReportEvidenceError",
    "build_report_body",
    "ensure_job_artifacts",
    "ensure_mock_job_artifacts",
    "ensure_real_job_artifacts",
    "ensure_job_pdf_artifact",
    "generate_and_persist_report",
    "generate_summary_text",
    "persist_report",
    "ensure_repro_manifest_artifact",
]
