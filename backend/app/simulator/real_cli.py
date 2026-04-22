"""Real external simulator adapter (Phase 8).

Invokes an external CLI subprocess (for example a Python or shell driver that
talks to PX4/Gazebo) once per trial. The adapter writes a structured
``trial_input.json`` describing the trial, waits for the subprocess to write a
matching ``trial_result.json``, and translates the result into the standard
:class:`TrialResult`/:class:`TrialFailure` shapes.

Environment variables:

* ``REAL_SIMULATOR_COMMAND`` — required. Either a command containing the
  literal tokens ``{input}`` and ``{output}`` (which will be string-formatted),
  or a bare command to which ``--input <trial_input.json> --output
  <trial_result.json>`` is appended.
* ``REAL_SIMULATOR_WORKDIR`` — optional working directory for the subprocess.
* ``REAL_SIMULATOR_TIMEOUT_SECONDS`` — wall-clock timeout, default 300.
* ``REAL_SIMULATOR_ARTIFACT_ROOT`` — root directory for per-trial run dirs,
  default ``./artifacts``.
* ``REAL_SIMULATOR_KEEP_RUN_DIRS`` — keep run dirs around after the trial
  finishes (default ``true``). Set ``false`` to delete successful runs.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    ArtifactMetadata,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialMetricsPayload,
    TrialResult,
)

logger = logging.getLogger("drone_dream.simulator.real_cli")

_DEFAULT_TIMEOUT = 300
_DEFAULT_ARTIFACT_ROOT = "./artifacts"


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, original length {len(text)}]"


def _build_command(
    command_template: str, input_path: Path, output_path: Path
) -> list[str]:
    if "{input}" in command_template or "{output}" in command_template:
        formatted = command_template.format(input=str(input_path), output=str(output_path))
        return shlex.split(formatted)
    tokens = shlex.split(command_template)
    tokens.extend(["--input", str(input_path), "--output", str(output_path)])
    return tokens


def _trial_input_payload(ctx: TrialContext, output_path: Path) -> dict[str, Any]:
    jc = ctx.job_config
    return {
        "trial_id": ctx.trial_id,
        "job_id": ctx.job_id,
        "candidate_id": ctx.candidate_id,
        "seed": ctx.seed,
        "scenario_type": ctx.scenario_type,
        "scenario_config": ctx.scenario_config or {},
        "job_config": {
            "track_type": jc.track_type,
            "start_point": {"x": jc.start_point_x, "y": jc.start_point_y},
            "altitude_m": jc.altitude_m,
            "wind": {
                "north": jc.wind_north,
                "east": jc.wind_east,
                "south": jc.wind_south,
                "west": jc.wind_west,
            },
            "sensor_noise_level": jc.sensor_noise_level,
            "objective_profile": jc.objective_profile,
        },
        "parameters": dict(ctx.parameters),
        "output_path": str(output_path),
    }


def _parse_metrics(raw: dict[str, Any]) -> TrialMetricsPayload:
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("missing 'metrics' object in trial_result.json")
    required = {"rmse", "max_error", "overshoot_count", "completion_time", "score"}
    missing = required - set(metrics)
    if missing:
        raise ValueError(f"metrics missing required keys: {sorted(missing)}")
    raw_metric_json = metrics.get("raw_metric_json")
    if raw_metric_json is not None and not isinstance(raw_metric_json, dict):
        raise ValueError("raw_metric_json must be an object when present")
    return TrialMetricsPayload(
        rmse=float(metrics["rmse"]),
        max_error=float(metrics["max_error"]),
        overshoot_count=int(metrics["overshoot_count"]),
        completion_time=float(metrics["completion_time"]),
        crash_flag=bool(metrics.get("crash_flag", False)),
        timeout_flag=bool(metrics.get("timeout_flag", False)),
        score=float(metrics["score"]),
        final_error=float(metrics.get("final_error", 0.0)),
        pass_flag=bool(metrics.get("pass_flag", False)),
        instability_flag=bool(metrics.get("instability_flag", False)),
        raw_metric_json=dict(raw_metric_json) if raw_metric_json else {},
    )


def _parse_artifacts(raw: dict[str, Any]) -> list[ArtifactMetadata]:
    artifacts_raw = raw.get("artifacts") or []
    if not isinstance(artifacts_raw, list):
        raise ValueError("'artifacts' must be an array")
    artifacts: list[ArtifactMetadata] = []
    for item in artifacts_raw:
        if not isinstance(item, dict):
            raise ValueError("each artifact must be an object")
        artifact_type = item.get("artifact_type")
        display_name = item.get("display_name")
        storage_path = item.get("storage_path")
        if not isinstance(artifact_type, str) or not isinstance(storage_path, str):
            raise ValueError("artifact requires 'artifact_type' and 'storage_path'")
        mime_type = item.get("mime_type")
        file_size = item.get("file_size_bytes")
        artifacts.append(
            ArtifactMetadata(
                artifact_type=artifact_type,
                display_name=display_name if isinstance(display_name, str) else artifact_type,
                storage_path=storage_path,
                mime_type=mime_type if isinstance(mime_type, str) else None,
                file_size_bytes=int(file_size) if isinstance(file_size, int) else None,
            )
        )
    return artifacts


class RealCliSimulatorAdapter(SimulatorAdapter):
    """Invoke an external CLI-based simulator via subprocess per trial."""

    backend_name = "real_cli"

    def run_trial(self, ctx: TrialContext) -> TrialResult:
        command_template = os.environ.get("REAL_SIMULATOR_COMMAND", "").strip()
        if not command_template:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=(
                        "REAL_SIMULATOR_COMMAND is not configured. Set it to the "
                        "external simulator CLI before using backend=real_cli."
                    ),
                ),
                log_excerpt="[real_cli] REAL_SIMULATOR_COMMAND unset",
            )

        artifact_root = Path(
            os.environ.get("REAL_SIMULATOR_ARTIFACT_ROOT", _DEFAULT_ARTIFACT_ROOT)
        )
        run_dir = artifact_root / "jobs" / ctx.job_id / "trials" / ctx.trial_id
        run_dir.mkdir(parents=True, exist_ok=True)

        input_path = run_dir / "trial_input.json"
        output_path = run_dir / "trial_result.json"

        payload = _trial_input_payload(ctx, output_path)
        with input_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        try:
            timeout = int(
                os.environ.get("REAL_SIMULATOR_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT))
            )
        except ValueError:
            timeout = _DEFAULT_TIMEOUT
        workdir = os.environ.get("REAL_SIMULATOR_WORKDIR") or None

        try:
            argv = _build_command(command_template, input_path, output_path)
        except ValueError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=FAILURE_ADAPTER_UNAVAILABLE, reason=str(exc)),
                log_excerpt=f"[real_cli] invalid REAL_SIMULATOR_COMMAND: {exc}",
            )

        logger.info(
            "real_cli trial=%s launching command=%s cwd=%s timeout=%ds",
            ctx.trial_id,
            argv,
            workdir,
            timeout,
        )

        try:
            proc = subprocess.run(  # noqa: S603 — trusted operator-supplied command
                argv,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            log = _truncate(
                "STDOUT:\n" + str(stdout) + "\nSTDERR:\n" + str(stderr)
            )
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_TIMEOUT,
                    reason=(
                        f"Real simulator exceeded timeout of {timeout}s "
                        f"for trial {ctx.trial_id}."
                    ),
                ),
                log_excerpt=log,
            )
        except FileNotFoundError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=f"Simulator executable not found: {exc}",
                ),
                log_excerpt=f"[real_cli] executable not found: {exc}",
            )

        combined_log = _truncate(
            f"[real_cli exit={proc.returncode}]\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

        if not output_path.exists():
            self._maybe_cleanup(run_dir, keep=True)
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=(
                        "Simulator exited without producing trial_result.json "
                        f"(exit={proc.returncode})."
                    ),
                ),
                log_excerpt=combined_log,
            )

        try:
            with output_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"trial_result.json was malformed: {exc}",
                ),
                log_excerpt=combined_log,
            )

        if not isinstance(raw, dict):
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason="trial_result.json must be a JSON object.",
                ),
                log_excerpt=combined_log,
            )

        log_excerpt = raw.get("log_excerpt")
        log_text = log_excerpt if isinstance(log_excerpt, str) and log_excerpt else combined_log

        if not bool(raw.get("success")):
            failure_raw = raw.get("failure") if isinstance(raw.get("failure"), dict) else {}
            if not isinstance(failure_raw, dict):
                failure_raw = {}
            code_value = failure_raw.get("code")
            code: str = code_value if isinstance(code_value, str) else FAILURE_SIMULATION
            reason_value = failure_raw.get("reason")
            reason: str = (
                reason_value
                if isinstance(reason_value, str)
                else "Simulator reported failure without a reason."
            )
            try:
                failure_artifacts = _parse_artifacts(raw)
            except ValueError:
                failure_artifacts = []
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=code, reason=reason),
                artifacts=failure_artifacts,
                log_excerpt=log_text,
            )

        try:
            metrics = _parse_metrics(raw)
            artifacts = _parse_artifacts(raw)
        except (ValueError, TypeError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"Malformed simulator output: {exc}",
                ),
                log_excerpt=combined_log,
            )

        self._maybe_cleanup(run_dir, keep=self._keep_run_dirs(success=True))
        logger.info(
            "real_cli trial=%s success score=%s rmse=%s",
            ctx.trial_id,
            metrics.score,
            metrics.rmse,
        )
        return TrialResult(
            success=True,
            backend=self.backend_name,
            metrics=metrics,
            artifacts=artifacts,
            log_excerpt=log_text,
        )

    @staticmethod
    def _keep_run_dirs(*, success: bool) -> bool:
        raw = os.environ.get("REAL_SIMULATOR_KEEP_RUN_DIRS", "true").strip().lower()
        keep = raw not in {"0", "false", "no", "off"}
        # Always keep failure run dirs so operators can inspect.
        return keep or not success

    @staticmethod
    def _maybe_cleanup(run_dir: Path, *, keep: bool) -> None:
        if keep:
            return
        try:
            shutil.rmtree(run_dir)
        except OSError:  # pragma: no cover — best-effort cleanup
            logger.warning("failed to clean run_dir %s", run_dir)


__all__ = ["RealCliSimulatorAdapter"]
