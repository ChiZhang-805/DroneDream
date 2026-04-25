"""PDF report generation for completed jobs (no third-party deps)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app import models

_SECRET_TOKENS = ("secret", "api_key", "token", "password", "key")


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "—"


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


def _paginate_lines(wrapped_lines: list[str], lines_per_page: int = 52) -> list[list[str]]:
    if not wrapped_lines:
        return [[]]
    return [
        wrapped_lines[i : i + lines_per_page]
        for i in range(0, len(wrapped_lines), lines_per_page)
    ]


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_page_stream(page_lines: list[str], page_number: int, page_count: int) -> bytes:
    stream_lines = [b"BT", b"/F1 10 Tf", b"50 800 Td", b"14 TL"]
    for line in page_lines:
        escaped = _escape_pdf_text(line)
        stream_lines.append(f"({escaped}) Tj".encode())
        stream_lines.append(b"T*")
    stream_lines.extend(
        [
            b"ET",
            b"BT",
            b"/F1 9 Tf",
            b"260 30 Td",
            f"(Page {page_number} / {page_count}) Tj".encode(),
            b"ET",
        ]
    )
    stream = b"\n".join(stream_lines)
    return (
        f"<< /Length {len(stream)} >>\nstream\n".encode()
        + stream
        + b"\nendstream"
    )


def _build_pdf(lines: list[str]) -> bytes:
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    wrapped_lines = _wrap_lines(lines)
    pages = _paginate_lines(wrapped_lines)
    page_count = len(pages)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_kids = " ".join(f"{5 + i * 2} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{page_kids}] /Count {page_count} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for idx, page_lines in enumerate(pages):
        stream_obj = _build_page_stream(
            page_lines,
            page_number=idx + 1,
            page_count=page_count,
        )
        objects.append(stream_obj)
        page_obj = (
            "<< /Type /Page /Parent 2 0 R "
            "/MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {4 + idx * 2} 0 R >>"
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
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
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

    add("")
    add("2) Initial job settings")
    add(f"- Track type: {job.track_type}")
    add(f"- Start point: ({job.start_point_x:.2f}, {job.start_point_y:.2f})")
    add(f"- Altitude: {job.altitude_m:.2f} m")
    wind_text = (
        f"- Wind N/E/S/W: {job.wind_north:.2f} / {job.wind_east:.2f} / "
        f"{job.wind_south:.2f} / {job.wind_west:.2f}"
    )
    add(wind_text)
    add(f"- Sensor noise level: {job.sensor_noise_level}")
    add(f"- Objective profile: {job.objective_profile}")
    add(f"- target_rmse: {_fmt_num(job.target_rmse, digits=3)}")
    add(f"- target_max_error: {_fmt_num(job.target_max_error, digits=3)}")
    add(f"- min_pass_rate: {_fmt_num(job.min_pass_rate, digits=3)}")

    baseline = next((c for c in job.candidates if c.id == job.baseline_candidate_id), None)
    baseline_agg = {}
    if baseline is not None and baseline.aggregated_metric_json is not None:
        baseline_agg = baseline.aggregated_metric_json

    add("")
    add("3) Baseline metrics")
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
    add(f"- Aggregated max_error: {_fmt_num(baseline_agg.get('max_error'), digits=3)} m")
    add(f"- Completion time: {_fmt_num(baseline_agg.get('completion_time'), digits=2)} s")
    score = baseline_agg.get("aggregated_score") or baseline_agg.get("score")
    add(f"- Score: {_fmt_num(score, digits=4)}")
    done = baseline_agg.get("completed_trial_count", 0)
    total = baseline_agg.get("trial_count", 0)
    add(f"- Trial count: {done}/{total}")

    add("")
    add("4) Candidate summary")
    sorted_candidates = sorted(
        job.candidates,
        key=lambda item: (item.generation_index, item.created_at),
    )
    for candidate in sorted_candidates:
        agg = candidate.aggregated_metric_json or {}
        params = candidate.parameter_json or {}
        is_base = "yes" if candidate.is_baseline else "no"
        header = (
            f"- {candidate.id} | label={candidate.label or '—'} | "
            f"source={candidate.source_type} | gen={candidate.generation_index} | "
            f"baseline={is_base} | best={'yes' if candidate.is_best else 'no'}"
        )
        add(header)
        focus_params = {
            "kp_xy": params.get("kp_xy"),
            "kd_xy": params.get("kd_xy"),
            "ki_xy": params.get("ki_xy"),
            "vel_limit": params.get("vel_limit"),
            "accel_limit": params.get("accel_limit"),
            "disturbance_rejection": params.get("disturbance_rejection"),
        }
        add(f"  params {_truncate(json.dumps(focus_params, ensure_ascii=False), limit=220)}")
        metrics_text = (
            f"  metrics rmse={_fmt_num(agg.get('rmse'), digits=3)} "
            f"max_error={_fmt_num(agg.get('max_error'), digits=3)} "
            f"completion={_fmt_num(agg.get('completion_time'), digits=2)}s "
            f"score={_fmt_num(agg.get('aggregated_score') or candidate.aggregated_score, digits=4)}"
        )
        add(metrics_text)
        rationale = _truncate(candidate.proposal_reason, limit=200)
        add(
            "  trials "
            f"{candidate.completed_trial_count}/{candidate.trial_count} "
            f"rationale={rationale or '—'}"
        )

    add("")
    add("5) Trial summary")
    trial_to_label = {c.id: c.label or c.id for c in job.candidates}
    for trial in sorted(job.trials, key=lambda item: item.created_at):
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

    best = next((c for c in job.candidates if c.id == job.best_candidate_id), None)
    best_agg = (best.aggregated_metric_json or {}) if best is not None else {}
    add("")
    add("6) Best parameters")
    add(f"- best candidate id: {best.id if best else '—'}")
    add(f"- best label: {best.label if best else '—'}")
    add(f"- best generation index: {best.generation_index if best else '—'}")
    metric_summary = (
        f"- best aggregated metrics: rmse={_fmt_num(best_agg.get('rmse'), digits=3)} m, "
        f"max_error={_fmt_num(best_agg.get('max_error'), digits=3)} m, "
        f"completion={_fmt_num(best_agg.get('completion_time'), digits=2)} s, "
        f"score={_fmt_num(best_agg.get('aggregated_score'), digits=4)}"
    )
    add(metric_summary)
    if best is not None:
        for key, value in _safe_pairs(best.parameter_json):
            add(f"  - {key}: {value}")

    fallback = (
        f"Job {job.id} finished with status {job.status}. "
        f"Best candidate: {job.best_candidate_id or 'N/A'}."
    )
    summary = (report.summary_text if report and report.summary_text else None) or fallback
    add("")
    add("7) Summary")
    add(summary)
    return lines


def generate_job_pdf_report(*, db: Session, job: models.Job, output_dir: Path) -> Path:
    """Generate a job PDF report and return its absolute path."""
    del db

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / f"{job.id} report.pdf").resolve()
    lines = build_job_report_lines(job)
    output_path.write_bytes(_build_pdf(lines))
    return output_path


__all__ = ["build_job_report_lines", "generate_job_pdf_report"]
