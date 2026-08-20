"""Sidecar model coordinator for non-blocking PX4 segment checkpoints."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .contracts import (
    PreparedMission,
    RuntimeAssessment,
    RuntimeCheckpoint,
    RuntimeCheckpointContract,
    RuntimeCheckpointDecision,
    RuntimeCheckpointRequest,
)
from .extensions import ExtensionExecutionError
from .hashing import sha256_json
from .model_port import ProviderName, StructuredModelPort
from .prompts import EXECUTION_MONITOR
from .runtime_plugins import (
    append_hook_receipts,
    augment_runtime_prompt,
    require_plugin_acceptance,
    runtime_extension_registry,
    validate_runtime_model_output,
)


def checkpoint_contract_for(prepared: PreparedMission) -> RuntimeCheckpointContract:
    if prepared.runtime_checkpoints is not None:
        return prepared.runtime_checkpoints
    checkpoints: list[RuntimeCheckpoint] = []
    point_index = 0
    for index, segment in enumerate(prepared.plan.segments, start=1):
        point_index += len(segment.path) - 1
        checkpoints.append(
            RuntimeCheckpoint(
                checkpoint_id=f"checkpoint-{index:03d}",
                segment_id=segment.segment_id,
                task_id=segment.task_id,
                track_point_index=point_index,
                target_node=segment.to_node,
            )
        )
    return RuntimeCheckpointContract(
        contract_id=prepared.contract.contract_id, checkpoints=checkpoints
    )


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    rendered = (
        payload.model_dump_json(indent=2)
        if hasattr(payload, "model_dump_json")
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
    temporary.write_text(rendered + "\n", encoding="utf-8")
    temporary.replace(path)


def checkpoint_continue_authorized(
    *,
    request: RuntimeCheckpointRequest,
    assessment: RuntimeAssessment,
    binding_gates: dict[str, bool],
) -> bool:
    """Apply the non-relaxable gate above a model checkpoint decision."""
    return (
        assessment.action == "accept"
        and all(request.deterministic_gates.values())
        and all(binding_gates.values())
    )


class CheckpointCoordinator:
    """Call the real execution-monitor model while the executor keeps hovering."""

    def __init__(
        self,
        *,
        prepared: PreparedMission,
        run_dir: Path,
        provider: ProviderName,
        abort_file: Path,
        model_timeout_seconds: float,
    ) -> None:
        self.prepared = prepared
        self.contract = checkpoint_contract_for(prepared)
        self.run_dir = run_dir
        self.abort_file = abort_file
        self.port = StructuredModelPort(
            provider, max_attempts=3, timeout_seconds=model_timeout_seconds
        )
        self.extensions = runtime_extension_registry(prepared)
        self.receipt_path = run_dir / "plugin-hook-receipts.jsonl"
        self.decisions: list[RuntimeCheckpointDecision] = []
        self.error: Exception | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="dronedream-checkpoint-coordinator", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        self._stop.set()
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise TimeoutError("checkpoint coordinator did not stop")

    def _request_abort(self, reason: str) -> None:
        if not self.abort_file.exists():
            _atomic_json(
                self.abort_file,
                {"reason": reason[:240], "world_paused": False},
            )

    def _run(self) -> None:
        try:
            segment_by_id = {segment.segment_id: segment for segment in self.prepared.plan.segments}
            for checkpoint in self.contract.checkpoints:
                request_path = (
                    self.run_dir / "checkpoints" / f"{checkpoint.checkpoint_id}.request.json"
                )
                decision_path = (
                    self.run_dir / "checkpoints" / f"{checkpoint.checkpoint_id}.decision.json"
                )
                while not request_path.is_file():
                    if self._stop.wait(0.05):
                        return
                request = RuntimeCheckpointRequest.model_validate_json(
                    request_path.read_text(encoding="utf-8")
                )
                if request.contract_id != self.prepared.contract.contract_id:
                    raise RuntimeError("checkpoint request contract mismatch")
                segment = segment_by_id[checkpoint.segment_id]
                point_index = checkpoint.track_point_index
                index_valid = point_index < len(self.prepared.px4_track.points)
                planned_point = self.prepared.px4_track.points[point_index] if index_valid else None
                expected_ned = (
                    {
                        "north_m": planned_point.x,
                        "east_m": planned_point.y,
                        "down_m": -planned_point.z,
                    }
                    if planned_point is not None
                    else None
                )
                commanded = request.commanded_position_ned_m
                command_matches = expected_ned is not None and all(
                    abs(observed - expected) <= 1e-8
                    for observed, expected in zip(
                        (commanded.x, commanded.y, commanded.z),
                        (
                            expected_ned["north_m"],
                            expected_ned["east_m"],
                            expected_ned["down_m"],
                        ),
                        strict=True,
                    )
                )
                binding_gates = {
                    "global_track_point_index_in_range": index_valid,
                    "checkpoint_target_matches_segment_endpoint": (
                        checkpoint.target_node == segment.to_node
                    ),
                    "px4_local_ned_command_matches_global_track_point": command_matches,
                }
                checkpoint_receipts = []
                try:
                    anomaly_outputs, anomaly_receipts = self.extensions.invoke_multiple(
                        "runtime.anomaly-detectors",
                        "evaluate_checkpoint",
                        request=request,
                        checkpoint=checkpoint,
                        segment=segment,
                        prepared=self.prepared,
                    )
                    checkpoint_receipts.extend(anomaly_receipts)
                    anomaly_gates, anomaly_evaluations = require_plugin_acceptance(
                        anomaly_outputs,
                        gate_prefix="plugin_anomaly",
                    )
                    binding_gates.update(anomaly_gates)
                    instructions, prompt_receipts = augment_runtime_prompt(
                        self.extensions,
                        role="execution_monitor",
                        instructions=EXECUTION_MONITOR,
                    )
                    checkpoint_receipts.extend(prompt_receipts)
                except ExtensionExecutionError as error:
                    append_hook_receipts(self.receipt_path, [error.receipt])
                    raise
                append_hook_receipts(self.receipt_path, checkpoint_receipts)
                result = self.port.call(
                    role="execution_monitor",
                    output_type=RuntimeAssessment,
                    instructions=instructions,
                    input_artifact={
                        "mission_contract": self.prepared.contract.model_dump(mode="json"),
                        "task_graph": self.prepared.task_graph.model_dump(mode="json"),
                        "segment_summary": {
                            "segment_id": segment.segment_id,
                            "task_id": segment.task_id,
                            "from_node": segment.from_node,
                            "to_node": segment.to_node,
                            "path_point_count": len(segment.path),
                            "path_sha256": sha256_json(segment.path),
                            "coordinate_frame": "School Map world ENU",
                        },
                        "checkpoint_request": request.model_dump(mode="json"),
                        "checkpoint_index_semantics": (
                            "global zero-based index within complete px4_track.points"
                        ),
                        "px4_coordinate_contract": (
                            self.prepared.px4_track.coordinate_contract.model_dump(mode="json")
                        ),
                        "expected_commanded_position_ned_m": expected_ned,
                        "code_computed_binding_gates": binding_gates,
                        "plugin_anomaly_evaluations": anomaly_evaluations,
                        "immutable_rule": (
                            "all deterministic gates must be true; model output has no "
                            "actuator authority"
                        ),
                    },
                    context_id=(f"{self.prepared.contract.conversation_id}::execution_monitor"),
                )
                try:
                    output_guard_receipts = validate_runtime_model_output(
                        self.extensions,
                        role="execution_monitor",
                        expected_schema=RuntimeAssessment.__name__,
                        artifact=result.artifact,
                        record=result.record,
                    )
                except ExtensionExecutionError as error:
                    append_hook_receipts(self.receipt_path, [error.receipt])
                    raise
                checkpoint_receipts.extend(output_guard_receipts)
                append_hook_receipts(self.receipt_path, output_guard_receipts)
                decision = RuntimeCheckpointDecision(
                    request_sha256=sha256_json(request),
                    assessment=result.artifact,
                    model_call=result.record,
                    continue_authorized=checkpoint_continue_authorized(
                        request=request,
                        assessment=result.artifact,
                        binding_gates=binding_gates,
                    ),
                    plugin_hook_receipts=checkpoint_receipts,
                )
                self.decisions.append(decision)
                _atomic_json(decision_path, decision)
                if not decision.continue_authorized:
                    self._request_abort(
                        f"MODEL_CHECKPOINT_{checkpoint.checkpoint_id}_"
                        f"{result.artifact.action.upper()}"
                    )
                    return
        except Exception as exc:
            self.error = exc
            self._request_abort(f"MODEL_CHECKPOINT_COORDINATOR_FAILURE_{type(exc).__name__}")
        finally:
            # Let filesystem observers consume the last atomic decision before exit.
            time.sleep(0.05)
