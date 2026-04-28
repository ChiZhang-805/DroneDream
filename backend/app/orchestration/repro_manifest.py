"""Reproducibility manifest generation for completed/failed jobs."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from app import models
from app.orchestration.constants import BASELINE_PARAMETERS, PARAMETER_SAFE_RANGES

_SAFE_ENV_ALLOWLIST: tuple[str, ...] = (
    "PX4_GAZEBO_WORLD",
    "PX4_GAZEBO_VEHICLE",
    "PX4_RUN_SECONDS",
    "REAL_SIMULATOR_ARTIFACT_ROOT",
    "PX4_AUTOPILOT_DIR",
)
_SENSITIVE_ENV_TOKENS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _fmt_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _find_repo_root(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _safe_git_output(repo_root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    out = proc.stdout.strip()
    return out or None


def _git_info() -> dict[str, Any]:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        return {
            "commit_hash": None,
            "branch": None,
            "dirty_working_tree": None,
        }

    commit_hash = _safe_git_output(repo_root, "rev-parse", "HEAD")
    branch = _safe_git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = _safe_git_output(repo_root, "status", "--porcelain")
    return {
        "commit_hash": commit_hash,
        "branch": branch,
        "dirty_working_tree": (bool(dirty) if dirty is not None else None),
    }


def _app_version() -> str:
    try:
        return metadata.version("drone-dream-backend")
    except Exception:
        return "0.1.0"


def _hash_or_redact_command(command: str | None) -> str | None:
    if not command:
        return None
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _px4_git_commit(px4_dir: str | None) -> str | None:
    if not px4_dir:
        return None
    root = Path(px4_dir).expanduser().resolve()
    if not root.exists():
        return None
    return _safe_git_output(root, "rev-parse", "HEAD")


def _selected_env_vars() -> dict[str, str]:
    selected: dict[str, str] = {}
    for name in _SAFE_ENV_ALLOWLIST:
        if any(token in name.upper() for token in _SENSITIVE_ENV_TOKENS):
            continue
        value = os.environ.get(name)
        if value is not None:
            selected[name] = value
    return selected


def _candidate_summaries(job: models.Job) -> list[dict[str, Any]]:
    rows = sorted(job.candidates, key=lambda c: (c.generation_index, c.created_at))
    return [
        {
            "id": c.id,
            "label": c.label,
            "generation": c.generation_index,
            "source": c.source_type,
            "aggregated_score": c.aggregated_score,
        }
        for c in rows
    ]


def _trial_summaries(job: models.Job) -> list[dict[str, Any]]:
    rows = sorted(job.trials, key=lambda t: t.created_at)
    return [
        {
            "trial_id": t.id,
            "candidate_id": t.candidate_id,
            "scenario_type": t.scenario_type,
            "seed": t.seed,
            "status": t.status,
            "metrics_summary": {
                "rmse": t.metric.rmse if t.metric is not None else None,
                "max_error": t.metric.max_error if t.metric is not None else None,
                "completion_time": t.metric.completion_time if t.metric is not None else None,
                "score": t.metric.score if t.metric is not None else None,
                "pass_flag": t.metric.pass_flag if t.metric is not None else None,
                "instability_flag": t.metric.instability_flag if t.metric is not None else None,
            },
        }
        for t in rows
    ]


def build_repro_manifest(*, job: models.Job, best: models.CandidateParameterSet) -> dict[str, Any]:
    git = _git_info()
    real_command = os.environ.get("REAL_SIMULATOR_COMMAND")
    px4_dir = os.environ.get("PX4_AUTOPILOT_DIR")
    return {
        "project": {
            "app_version": _app_version(),
            "git_commit_hash": git["commit_hash"],
            "git_branch": git["branch"],
            "dirty_working_tree": git["dirty_working_tree"],
        },
        "job": {
            "job_id": job.id,
            "created_at": _fmt_dt(job.created_at),
            "completed_at": _fmt_dt(job.completed_at),
            "track_type": job.track_type,
            "start_point": {"x": job.start_point_x, "y": job.start_point_y},
            "altitude": job.altitude_m,
            "wind": {
                "north": job.wind_north,
                "east": job.wind_east,
                "south": job.wind_south,
                "west": job.wind_west,
            },
            "sensor_noise": job.sensor_noise_level,
            "objective_profile": job.objective_profile,
            "simulator_backend_requested": job.simulator_backend_requested,
            "optimizer_strategy": job.optimizer_strategy,
            "max_iterations": job.max_iterations,
            "trials_per_candidate": job.trials_per_candidate,
            "max_total_trials": job.max_total_trials,
            "acceptance_criteria": {
                "target_rmse": job.target_rmse,
                "target_max_error": job.target_max_error,
                "min_pass_rate": job.min_pass_rate,
            },
        },
        "optimizer": {
            "parameter_safe_ranges": {
                key: {"min": lo, "max": hi}
                for key, (lo, hi) in PARAMETER_SAFE_RANGES.items()
            },
            "baseline_parameters": dict(BASELINE_PARAMETERS),
            "best_candidate_id": best.id,
            "best_parameters": dict(best.parameter_json or {}),
            "candidate_summaries": _candidate_summaries(job),
        },
        "simulator": {
            "real_simulator_command": _hash_or_redact_command(real_command),
            "real_simulator_artifact_root": os.environ.get("REAL_SIMULATOR_ARTIFACT_ROOT"),
            "px4_autopilot_dir": px4_dir,
            "px4_git_commit": _px4_git_commit(px4_dir),
        },
        "llm": {
            "openai_model": job.openai_model,
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "selected_env_vars": _selected_env_vars(),
        },
        "trials": _trial_summaries(job),
    }


__all__ = ["build_repro_manifest"]
