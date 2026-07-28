"""PDF report generation for completed jobs (no third-party deps)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app import models
from app.optimization.outcome_evidence import (
    require_authoritative_candidate_report_projection,
)
from app.orchestration.acceptance import criteria_for_job, evaluate_candidate
from app.orchestration.winner_freeze import require_winner_freeze_receipt
from app.time_utils import canonical_utc_iso

_SECRET_TOKENS = (
    "secret",
    "api_key",
    "token",
    "password",
    "key",
    "credential",
    "authorization",
    "bearer",
    "cookie",
)


def _worst_max_error(aggregate: dict[str, Any]) -> Any:
    return aggregate.get("max_error_worst", aggregate.get("max_error"))


def _fmt_dt(value: datetime | None) -> str:
    return canonical_utc_iso(value) or "—"


def _fmt_num(value: Any, *, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def _truncate(value: str | None, *, limit: int = 120) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, inner in value.items():
            lower = key.lower()
            if any(token in lower for token in _SECRET_TOKENS):
                continue
            clean[key] = _sanitize_value(inner)
        return clean
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _safe_pairs(payload: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not payload:
        return []
    rows: list[tuple[str, str]] = []
    for key in sorted(payload):
        lower = key.lower()
        if any(token in lower for token in _SECRET_TOKENS):
            continue
        value = _sanitize_value(payload[key])
        if isinstance(value, float):
            rows.append((key, f"{value:.4f}"))
        elif isinstance(value, (dict, list)):
            body = json.dumps(value, ensure_ascii=False)
            rows.append((key, _truncate(body, limit=200)))
        else:
            rows.append((key, str(value)))
    return rows


def _wrap_lines(lines: list[str], width: int = 105) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if len(line) <= width:
            wrapped.append(line)
            continue
        rest = line
        while len(rest) > width:
            split = rest.rfind(" ", 0, width)
            if split <= 0:
                split = width
            wrapped.append(rest[:split])
            rest = rest[split:].lstrip()
        if rest:
            wrapped.append(rest)
    return wrapped


def _pct_change(old: Any, new: Any) -> str:
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return "—"
    if old == 0:
        return "—"
    return f"{((new - old) / old) * 100.0:+.1f}%"


def _parameter_changes(
    parent: models.CandidateParameterSet | None,
    candidate: models.CandidateParameterSet,
) -> list[str]:
    """Describe only parameter changes that are explicitly bound to a parent."""

    if parent is None:
        return []
    parent_values = dict(_safe_pairs(parent.parameter_json))
    candidate_values = dict(_safe_pairs(candidate.parameter_json))
    changes: list[str] = []
    for key in sorted(set(parent_values) | set(candidate_values)):
        old = parent_values.get(key, "—")
        new = candidate_values.get(key, "—")
        if old == new:
            continue
        changes.append(f"{key}: {old} -> {new}")
    return changes


def _collect_artifacts(job: models.Job) -> tuple[list[models.Artifact], list[models.Artifact]]:
    session = object_session(job)
    if session is None:
        return [], []
    job_artifacts = list(
        session.scalars(
            select(models.Artifact)
            .where(models.Artifact.owner_type == "job")
            .where(models.Artifact.owner_id == job.id)
            # A report cannot include its own byte size without making the
            # report recursively self-dependent and non-deterministic.
            .where(models.Artifact.artifact_type != "pdf_report")
            .order_by(models.Artifact.artifact_type.asc(), models.Artifact.id.asc())
        ).all()
    )
    trial_ids = [t.id for t in job.trials]
    if not trial_ids:
        return job_artifacts, []
    trial_artifacts = list(
        session.scalars(
            select(models.Artifact)
            .where(models.Artifact.owner_type == "trial")
            .where(models.Artifact.owner_id.in_(trial_ids))
            .order_by(models.Artifact.artifact_type.asc(), models.Artifact.id.asc())
        ).all()
    )
    return job_artifacts, trial_artifacts


def _paginate_lines(wrapped_lines: list[str], lines_per_page: int = 52) -> list[list[str]]:
    if not wrapped_lines:
        return [[]]
    return [
        wrapped_lines[i : i + lines_per_page] for i in range(0, len(wrapped_lines), lines_per_page)
    ]


def _pdf_text_operand(text: str) -> bytes:
    """Encode Unicode for the predefined Adobe GB1 CID font.

    Literal PDF strings plus Helvetica only render Latin text. DroneDream job
    names, errors, and summaries are routinely Chinese, so use UTF-16BE hex
    strings with the standard ``UniGB-UCS2-H`` CMap instead of emitting broken
    UTF-8 bytes into a Helvetica content stream.
    """

    return f"<{text.encode('utf-16-be').hex().upper()}> Tj".encode("ascii")


def _free_report_watermark_stream() -> list[bytes]:
    """Draw a non-official, semi-transparent DroneDream brand seal.

    The purple/magenta rings and stylized bat deliberately avoid the red,
    star-shaped, organization-name, and registration-number conventions of a
    government or legal seal. The mark overlaps the lower-right body region at
    low opacity so it remains visible without obscuring the report.
    """

    return [
        b"% DD-FREE-REPORT-WATERMARK-V1",
        b"q",
        b"/GSW gs",
        b"2.4 w",
        b"0.45 0.16 0.88 RG",
        # Outer circle, centered at (492, 118), radius 64.
        b"492 182 m",
        b"527.35 182 556 153.35 556 118 c",
        b"556 82.65 527.35 54 492 54 c",
        b"456.65 54 428 82.65 428 118 c",
        b"428 153.35 456.65 182 492 182 c S",
        b"1.3 w",
        b"0.92 0.17 0.57 RG",
        # Inner circle.
        b"492 174 m",
        b"522.93 174 548 148.93 548 118 c",
        b"548 87.07 522.93 62 492 62 c",
        b"461.07 62 436 87.07 436 118 c",
        b"436 148.93 461.07 174 492 174 c S",
        # Minimal bat silhouette: two wings, a compact body, and pointed ears.
        b"0.48 0.18 0.90 rg",
        b"492 129 m",
        b"480 143 463 148 447 143 c",
        b"455 134 458 123 455 111 c",
        b"469 116 479 111 486 101 c",
        b"489 96 490 91 492 84 c",
        b"494 91 495 96 498 101 c",
        b"505 111 515 116 529 111 c",
        b"526 123 529 134 537 143 c",
        b"521 148 504 143 492 129 c f",
        # Ears and head.
        b"486 132 m 487 142 l 492 137 l 497 142 l 498 132 l h f",
        b"BT",
        b"/F1 7 Tf",
        b"0.45 0.16 0.88 rg",
        b"455 159 Td",
        _pdf_text_operand("DRONE DREAM"),
        b"ET",
        b"BT",
        b"/F1 7 Tf",
        b"0.92 0.17 0.57 rg",
        b"458 71 Td",
        _pdf_text_operand("FREE EXPORT"),
        b"ET",
        b"Q",
    ]


def _build_page_stream(
    page_lines: list[str],
    page_number: int,
    page_count: int,
    *,
    free_tier_watermark: bool,
) -> bytes:
    stream_lines = [b"BT", b"/F1 10 Tf", b"50 800 Td", b"14 TL"]
    for line in page_lines:
        stream_lines.append(_pdf_text_operand(line))
        stream_lines.append(b"T*")
    stream_lines.extend(
        [
            b"ET",
            b"BT",
            b"/F1 9 Tf",
            b"260 30 Td",
            _pdf_text_operand(f"Page {page_number} / {page_count}"),
            b"ET",
        ]
    )
    if free_tier_watermark:
        stream_lines.extend(_free_report_watermark_stream())
    stream = b"\n".join(stream_lines)
    return f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"


def _build_pdf(lines: list[str], *, free_tier_watermark: bool = False) -> bytes:
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    wrapped_lines = _wrap_lines(lines)
    pages = _paginate_lines(wrapped_lines)
    page_count = len(pages)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_kids = " ".join(f"{7 + i * 2} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{page_kids}] /Count {page_count} >>".encode())
    objects.append(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>"
    )
    objects.append(
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>"
    )
    objects.append(b"<< /Type /ExtGState /CA 0.18 /ca 0.18 >>")

    for idx, page_lines in enumerate(pages):
        stream_obj = _build_page_stream(
            page_lines,
            page_number=idx + 1,
            page_count=page_count,
            free_tier_watermark=free_tier_watermark,
        )
        objects.append(stream_obj)
        page_obj = (
            "<< /Type /Page /Parent 2 0 R "
            "/MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 3 0 R >> "
            "/ExtGState << /GSW 5 0 R >> >> "
            f"/Contents {6 + idx * 2} 0 R >>"
        ).encode()
        objects.append(page_obj)

    xref: list[int] = [0]
    for idx, obj in enumerate(objects, start=1):
        xref.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_start = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in xref[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    )
    out.extend(trailer.encode("ascii"))
    return bytes(out)


def build_job_report_lines(job: models.Job) -> list[str]:
    """Build human-readable report lines prior to PDF rendering."""
    report = job.report
    lines: list[str] = []
    add = lines.append

    add("DroneDream Job Report")
    add("")
    add("1) Metadata")
    add(f"- Job ID: {job.id}")
    add(f"- Created at: {_fmt_dt(job.created_at)}")
    add(f"- Updated/completed at: {_fmt_dt(job.completed_at or job.updated_at)}")
    add(f"- Status: {job.status}")
    add(f"- Simulator backend: {job.simulator_backend_requested}")
    add(f"- Optimizer strategy: {job.optimizer_strategy}")
    add(f"- OpenAI model: {job.openai_model or '—'}")
    add(f"- Optimization outcome: {job.optimization_outcome or '—'}")
    add(f"- Current generation / max iterations: {job.current_generation} / {job.max_iterations}")
    add(f"- Trials per candidate: {job.trials_per_candidate}")

    baseline = next((c for c in job.candidates if c.id == job.baseline_candidate_id), None)
    baseline_agg = {}
    if baseline is not None:
        baseline_agg = require_authoritative_candidate_report_projection(baseline)
    best = next((c for c in job.candidates if c.id == job.best_candidate_id), None)
    best_agg = require_authoritative_candidate_report_projection(best) if best is not None else {}

    add("")
    add("2) Executive summary")
    add(f"- Job status: {job.status}")
    add(f"- Optimization outcome: {job.optimization_outcome or '—'}")
    add(f"- Best candidate: {(best.label if best else '—')} / {(best.id if best else '—')}")
    verified_winner = (
        require_winner_freeze_receipt(
            report.winner_freeze_receipt,
            job=job,
            evidence=report.winner_evidence_json,
        )
        if report is not None and report.winner_freeze_receipt is not None
        else None
    )
    winner_evidence = (
        verified_winner.model_dump(mode="json")
        if verified_winner is not None
        else (
            report.winner_evidence_json
            if report is not None and isinstance(report.winner_evidence_json, dict)
            else {}
        )
    )
    add(
        f"- Winner selection evidence: {winner_evidence.get('evidence_id', 'legacy / unavailable')}"
    )
    winner_freeze_receipt_id = (
        report.winner_freeze_receipt_id
        if report is not None and report.winner_freeze_receipt_id
        else "legacy / unavailable"
    )
    add(f"- Winner freeze receipt: {winner_freeze_receipt_id}")
    add(
        "- Baseline vs best RMSE change: "
        f"{_pct_change(baseline_agg.get('rmse'), best_agg.get('rmse'))}"
    )
    add(
        "- Baseline vs best worst max_error change: "
        f"{_pct_change(_worst_max_error(baseline_agg), _worst_max_error(best_agg))}"
    )
    add(
        "- Baseline vs best completion_time change: "
        f"{_pct_change(baseline_agg.get('completion_time'), best_agg.get('completion_time'))}"
    )

    add("")
    add("3) Initial job settings")
    add(f"- Track type: {job.track_type}")
    reference_track = (
        [p for p in (job.reference_track_json or []) if isinstance(p, dict)]
        if job.reference_track_json
        else []
    )
    if reference_track:
        preview = reference_track[:5]
        add(f"- Custom track points: {len(reference_track)} total")
        preview_text = json.dumps(preview, ensure_ascii=False)
        add(f"- Custom track preview (first {len(preview)}): {preview_text}")
    elif job.track_type == "custom":
        add("- Custom track points: 0 total")
    add(f"- Start point: ({job.start_point_x:.2f}, {job.start_point_y:.2f})")
    add(f"- Altitude: {job.altitude_m:.2f} m")
    wind_text = (
        f"- Wind N/E/S/W: {job.wind_north:.2f} / {job.wind_east:.2f} / "
        f"{job.wind_south:.2f} / {job.wind_west:.2f}"
    )
    add(wind_text)
    add(f"- Sensor noise level: {job.sensor_noise_level}")
    add(f"- Objective profile: {job.objective_profile}")
    advanced: dict[str, Any] = dict(job.advanced_scenario_config_json or {})
    add(f"- Advanced scenario enabled: {'yes' if bool(advanced) else 'no'}")
    if advanced:
        gust_raw = advanced.get("wind_gusts")
        sensor_raw = advanced.get("sensor_degradation")
        battery_raw = advanced.get("battery")
        obstacles_raw = advanced.get("obstacles")
        gust: dict[str, Any] = gust_raw if isinstance(gust_raw, dict) else {}
        sensor_deg: dict[str, Any] = sensor_raw if isinstance(sensor_raw, dict) else {}
        battery: dict[str, Any] = battery_raw if isinstance(battery_raw, dict) else {}
        obstacles: list[Any] = obstacles_raw if isinstance(obstacles_raw, list) else []
        add(
            "- Advanced summary: "
            f"gust_enabled={bool(gust.get('enabled', False))}, "
            f"gust_magnitude={_fmt_num(gust.get('magnitude_mps'), digits=2)}, "
            f"gust_direction={_fmt_num(gust.get('direction_deg'), digits=1)}, "
            f"obstacles={len(obstacles)}, "
            f"dropout_rate={_fmt_num(sensor_deg.get('dropout_rate'), digits=3)}, "
            f"battery_initial={_fmt_num(battery.get('initial_percent'), digits=1)}, "
            f"payload_kg={_fmt_num(battery.get('mass_payload_kg'), digits=2)}"
        )
    add(f"- target_rmse: {_fmt_num(job.target_rmse, digits=3)}")
    add(f"- target_max_error: {_fmt_num(job.target_max_error, digits=3)}")
    add(f"- min_pass_rate: {_fmt_num(job.min_pass_rate, digits=3)}")

    add("")
    add("4) Acceptance criteria")
    add(f"- target_rmse: {_fmt_num(job.target_rmse, digits=3)}")
    add(f"- target_max_error: {_fmt_num(job.target_max_error, digits=3)}")
    add(f"- min_pass_rate: {_fmt_num(job.min_pass_rate, digits=3)}")
    acceptance = evaluate_candidate(best, criteria_for_job(job)) if best is not None else None
    add(
        "- Best candidate meets acceptance: "
        f"{'yes' if acceptance is not None and acceptance.passed else 'no'}"
    )
    if acceptance is not None:
        add(
            "  - evaluator="
            f"{acceptance.reason}, pass_rate={_fmt_num(acceptance.pass_rate, digits=3)}, "
            f"completion_rate={_fmt_num(acceptance.completion_rate, digits=3)}, "
            f"rmse={_fmt_num(acceptance.rmse, digits=3)}, "
            f"worst_max_error={_fmt_num(acceptance.max_error, digits=3)}"
        )
    holdout = best_agg.get("holdout")
    if isinstance(holdout, dict):
        add(
            "- Holdout validation: "
            f"status={holdout.get('validation_status', 'unknown')}, "
            f"feasible={_fmt_num(holdout.get('feasible'))}, "
            f"completed={holdout.get('completed_trial_count', 0)}/"
            f"{holdout.get('trial_count', 0)}, "
            f"pass_rate={_fmt_num(holdout.get('pass_rate'), digits=3)}, "
            f"failure_rate={_fmt_num(holdout.get('failure_rate'), digits=3)}"
        )
        generalization = holdout.get("generalization_evidence")
        if isinstance(generalization, dict):
            shift_axes = generalization.get("shift_axes")
            axes_text = (
                ", ".join(str(item) for item in shift_axes)
                if isinstance(shift_axes, list)
                else "unknown"
            )
            relative_gap = generalization.get("scalar_loss_relative_degradation")
            relative_gap_text = (
                f"{_fmt_num(float(relative_gap) * 100.0, digits=2)}%"
                if isinstance(relative_gap, int | float) and not isinstance(relative_gap, bool)
                else "—"
            )
            add(
                "- Generalization evidence: "
                f"assessment={generalization.get('assessment', 'unknown')}, "
                f"scope={generalization.get('claim_scope', 'unknown')}, "
                f"shift={generalization.get('observed_shift', 'not_assessable')}, "
                f"axes={axes_text}, "
                f"scalar_loss_degradation={relative_gap_text}"
            )
            objective_gaps = generalization.get("objective_gaps")
            if isinstance(objective_gaps, list):
                for item in objective_gaps:
                    if not isinstance(item, dict):
                        continue
                    relative = item.get("relative_degradation")
                    relative_text = (
                        f"{_fmt_num(float(relative) * 100.0, digits=2)}%"
                        if isinstance(relative, int | float) and not isinstance(relative, bool)
                        else "—"
                    )
                    add(
                        "  - "
                        f"{item.get('metric', 'unknown')}: "
                        f"training={_fmt_num(item.get('training_value'), digits=4)}, "
                        f"validation={_fmt_num(item.get('validation_value'), digits=4)}, "
                        f"directional_degradation={relative_text}"
                    )

    add("")
    add("5) Baseline metrics")
    add(f"- Baseline candidate id: {baseline.id if baseline else '—'}")
    if baseline is not None:
        baseline_pairs = _safe_pairs(baseline.parameter_json)
        if baseline_pairs:
            add("- Baseline parameters:")
            for key, value in baseline_pairs:
                add(f"  - {key}: {value}")
        else:
            add("- Baseline parameters: —")
    else:
        add("- Baseline parameters: —")
    add(f"- Aggregated RMSE: {_fmt_num(baseline_agg.get('rmse'), digits=3)} m")
    add(f"- Mean max_error: {_fmt_num(baseline_agg.get('max_error'), digits=3)} m")
    add(f"- Worst max_error: {_fmt_num(_worst_max_error(baseline_agg), digits=3)} m")
    add(f"- Completion time: {_fmt_num(baseline_agg.get('completion_time'), digits=2)} s")
    score = baseline_agg.get("aggregated_score")
    if score is None:
        score = baseline_agg.get("score")
    add(f"- Score: {_fmt_num(score, digits=4)}")
    done = baseline_agg.get("completed_trial_count", 0)
    total = baseline_agg.get("trial_count", 0)
    add(f"- Trial count: {done}/{total}")

    add("")
    add("6) Iteration-by-iteration optimization trace")
    sorted_candidates = sorted(
        job.candidates,
        key=lambda item: (
            item.generation_index,
            canonical_utc_iso(item.created_at) or "",
            item.id,
        ),
    )
    candidate_by_id = {candidate.id: candidate for candidate in sorted_candidates}
    for candidate in sorted_candidates:
        agg = require_authoritative_candidate_report_projection(candidate)
        is_base = "yes" if candidate.is_baseline else "no"
        header = (
            f"- {candidate.id} | label={candidate.label or '—'} | "
            f"source={candidate.source_type} | gen={candidate.generation_index} | "
            f"baseline={is_base} | best={'yes' if candidate.is_best else 'no'}"
        )
        add(header)
        if candidate.is_baseline:
            add("  declared parent: baseline has no parent")
            changes: list[str] = []
        else:
            parent = (
                candidate_by_id.get(candidate.parent_candidate_id)
                if candidate.parent_candidate_id
                else None
            )
            if parent is None:
                add(
                    "  declared parent: unavailable; this report does not infer a causal "
                    "parameter lineage"
                )
                changes = []
            else:
                add(
                    f"  declared parent: {parent.id} / {parent.label or '—'} "
                    f"(generation {parent.generation_index})"
                )
                changes = _parameter_changes(parent, candidate)
        if changes:
            add(f"  recorded parameter changes ({len(changes)}):")
            for change in changes:
                add(f"    - {_truncate(change, limit=220)}")
        elif candidate.is_baseline:
            add("  recorded parameter changes: baseline snapshot")
        else:
            add("  recorded parameter changes: none attributable from stored parent evidence")
        parameter_snapshot = dict(_safe_pairs(candidate.parameter_json))
        add(
            "  resulting parameter snapshot: "
            f"{_truncate(json.dumps(parameter_snapshot, ensure_ascii=False), limit=260)}"
        )
        aggregate_score = agg.get("aggregated_score")
        if aggregate_score is None:
            aggregate_score = candidate.aggregated_score
        add(
            "  observed simulation feedback: "
            f"rmse={_fmt_num(agg.get('rmse'), digits=3)} "
            f"worst_max_error={_fmt_num(_worst_max_error(agg), digits=3)} "
            f"completion={_fmt_num(agg.get('completion_time'), digits=2)}s "
            f"score={_fmt_num(aggregate_score, digits=4)} "
            f"completed={candidate.completed_trial_count}/{candidate.trial_count} "
            f"failed={candidate.failed_trial_count}"
        )
        rationale = _truncate(candidate.proposal_reason, limit=200)
        add(f"  recorded proposal rationale (not inferred by the report): {rationale or '—'}")

    add("")
    add("7) Trial summary")
    trial_to_label = {c.id: c.label or c.id for c in job.candidates}
    for trial in sorted(
        job.trials,
        key=lambda item: (
            canonical_utc_iso(item.created_at) or "",
            item.id,
        ),
    ):
        metric = trial.metric
        candidate_label = trial_to_label.get(trial.candidate_id, "—")
        header = (
            f"- {trial.id} | candidate={trial.candidate_id}/{candidate_label} "
            f"| scenario={trial.scenario_type} | seed={trial.seed} | status={trial.status}"
        )
        add(header)
        details = (
            f"  pass={_fmt_num(metric.pass_flag if metric else None)} "
            f"rmse={_fmt_num(metric.rmse if metric else None, digits=3)} "
            f"max_error={_fmt_num(metric.max_error if metric else None, digits=3)} "
            f"final_error={_fmt_num(metric.final_error if metric else None, digits=3)} "
            f"completion={_fmt_num(metric.completion_time if metric else None, digits=2)}s "
            f"score={_fmt_num(metric.score if metric else None, digits=4)} "
            f"instability={_fmt_num(metric.instability_flag if metric else None)} "
            f"failure={trial.failure_code or '—'}"
        )
        add(details)

    add("")
    add("8) Best parameters")
    add(f"- best candidate id: {best.id if best else '—'}")
    add(f"- best label: {best.label if best else '—'}")
    add(f"- best generation index: {best.generation_index if best else '—'}")
    metric_summary = (
        f"- best aggregated metrics: rmse={_fmt_num(best_agg.get('rmse'), digits=3)} m, "
        f"worst_max_error={_fmt_num(_worst_max_error(best_agg), digits=3)} m, "
        f"completion={_fmt_num(best_agg.get('completion_time'), digits=2)} s, "
        f"score={_fmt_num(best_agg.get('aggregated_score'), digits=4)}"
    )
    add(metric_summary)
    if best is not None:
        for key, value in _safe_pairs(best.parameter_json):
            add(f"  - {key}: {value}")

    add("")
    add("9) Artifact index")
    job_artifacts, trial_artifacts = _collect_artifacts(job)
    if job_artifacts:
        for artifact in job_artifacts:
            add(
                "- "
                f"{artifact.artifact_type} | {artifact.display_name or '—'} | "
                f"{artifact.mime_type or '—'} | "
                f"size={artifact.file_size_bytes if artifact.file_size_bytes is not None else '—'}"
            )
    else:
        add("- Job-level artifacts: —")
    trial_counts: dict[str, int] = {}
    for artifact in trial_artifacts:
        trial_counts[artifact.artifact_type] = trial_counts.get(artifact.artifact_type, 0) + 1
    if trial_counts:
        add("- Trial-level artifact counts:")
        for artifact_type in sorted(trial_counts):
            add(f"  - {artifact_type}: {trial_counts[artifact_type]}")
    else:
        add("- Trial-level artifact counts: —")

    add("")
    add("10) Failure appendix")
    failed_trials = sorted(
        (trial for trial in job.trials if trial.status == "FAILED"),
        key=lambda trial: (
            canonical_utc_iso(trial.created_at) or "",
            trial.id,
        ),
    )
    if job.status == "FAILED":
        add(
            "- Job failure: "
            f"code={job.latest_error_code or '—'} "
            f"reason={_truncate(job.latest_error_message, limit=180) or '—'}"
        )
    else:
        add("- Job failure: —")
    if failed_trials:
        for trial in failed_trials:
            add(
                "- Trial failure: "
                f"{trial.id} code={trial.failure_code or '—'} "
                f"reason={_truncate(trial.failure_reason, limit=180) or '—'}"
            )
    else:
        add("- Trial failures: —")

    add("")
    add("11) Reproducibility note")
    repro_artifact = next(
        (a for a in job_artifacts if a.artifact_type == "repro_manifest_json"),
        None,
    )
    if repro_artifact is None:
        add("- Reproducibility manifest artifact: —")
    else:
        add(f"- Reproducibility manifest artifact available: {repro_artifact.display_name or '—'}")
        add("- Download from artifact list; PDF omits full manifest payload by design.")

    fallback = (
        f"Job {job.id} finished with status {job.status}. "
        f"Best candidate: {job.best_candidate_id or 'N/A'}."
    )
    summary = (report.summary_text if report and report.summary_text else None) or fallback
    add("")
    add("12) Summary")
    add(summary)
    return lines


def generate_job_pdf_report(*, db: Session, job: models.Job, output_dir: Path) -> Path:
    """Generate a job PDF report and return its absolute path."""
    del db

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / f"{job.id} report.pdf").resolve()
    output_path.write_bytes(render_job_pdf_report(job))
    return output_path


def render_job_pdf_report(
    job: models.Job,
    *,
    free_tier_watermark: bool = False,
) -> bytes:
    """Render deterministic PDF bytes without mutating artifact storage."""

    return _build_pdf(
        build_job_report_lines(job),
        free_tier_watermark=free_tier_watermark,
    )


__all__ = [
    "build_job_report_lines",
    "generate_job_pdf_report",
    "render_job_pdf_report",
]
