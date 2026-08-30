"""Confirmed execution of a prepared mission in the real PX4/Gazebo/ROS stack."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .assets import load_school_map_catalog
from .checkpointing import CheckpointCoordinator, checkpoint_contract_for
from .context import ContextStore
from .contracts import (
    CompletionAssessment,
    GraphRoute,
    MapAsset,
    MissionLifecycleBinding,
    PreparedMission,
    Px4GazeboRunEvidence,
    Px4Track,
    RouteClearanceReport,
    RuntimeCheckpointDecision,
    RuntimeInterruptionDecision,
    SimulationWorkflowResult,
    VehicleAsset,
)
from .evidence import EvidenceChain
from .extensions import ExtensionExecutionError
from .gazebo_adapter import run_px4_gazebo_track
from .hashing import sha256_json
from .model_port import ProviderName, StructuredModelPort
from .prompts import COMPLETION_VERIFIER
from .runtime_interrupt import (
    RuntimeInterruptionCoordinator,
    close_runtime_control_session,
    create_runtime_control_session,
)
from .runtime_plugins import (
    append_hook_receipts,
    augment_runtime_prompt,
    require_plugin_acceptance,
    runtime_extension_registry,
    validate_runtime_model_output,
)


class PreparedMissionBindingError(RuntimeError):
    """The confirmed package no longer matches its structured artifacts or assets."""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_package(
    prepared_path: Path,
    confirm_contract_id: str,
    semantic_path: Path,
    vehicle_sdf: Path,
) -> tuple[PreparedMission, Path, Path, Path, GraphRoute, RouteClearanceReport, Px4Track]:
    prepared = PreparedMission.model_validate_json(prepared_path.read_text(encoding="utf-8"))
    if confirm_contract_id != prepared.contract.contract_id:
        raise PreparedMissionBindingError("CONFIRMATION_CONTRACT_ID_MISMATCH")
    if prepared.status != "awaiting_confirmation":
        raise PreparedMissionBindingError("PREPARED_MISSION_NOT_CONFIRMABLE")
    if _file_sha256(semantic_path) != prepared.contract.map_semantic_sha256:
        raise PreparedMissionBindingError("SEMANTIC_ASSET_HASH_MISMATCH")
    if _file_sha256(vehicle_sdf) != prepared.contract.vehicle_sha256:
        raise PreparedMissionBindingError("VEHICLE_ASSET_HASH_MISMATCH")

    package_dir = prepared_path.parent
    route_path = package_dir / "08-execution-route.json"
    clearance_path = package_dir / "09-route-clearance.json"
    track_path = package_dir / "10-px4-track.json"
    route = GraphRoute.model_validate_json(route_path.read_text(encoding="utf-8"))
    clearance = RouteClearanceReport.model_validate_json(clearance_path.read_text(encoding="utf-8"))
    track = Px4Track.model_validate_json(track_path.read_text(encoding="utf-8"))
    if route != prepared.execution_route or sha256_json(route) != clearance.route_sha256:
        raise PreparedMissionBindingError("ROUTE_PACKAGE_BINDING_MISMATCH")
    if clearance != prepared.route_clearance or not clearance.accepted:
        raise PreparedMissionBindingError("CLEARANCE_PACKAGE_BINDING_MISMATCH")
    if track != prepared.px4_track:
        raise PreparedMissionBindingError("TRACK_PACKAGE_BINDING_MISMATCH")
    return prepared, route_path, clearance_path, track_path, route, clearance, track


def _execution_lifecycle_binding(
    *, prepared_path: Path, prepared: PreparedMission, context_store: ContextStore
) -> MissionLifecycleBinding:
    prepared_hash = sha256_json(prepared)
    sidecar_path = prepared_path.parent / "mission-lifecycle.json"
    if sidecar_path.is_file():
        binding = MissionLifecycleBinding.model_validate_json(
            sidecar_path.read_text(encoding="utf-8")
        )
        gates = {
            "conversation": (binding.thread.conversation_id == prepared.contract.conversation_id),
            "mission": binding.thread.mission_id == binding.plan_revision.mission_id,
            "current_revision": (
                binding.thread.current_plan_revision_id == binding.plan_revision.plan_revision_id
            ),
            "contract": binding.plan_revision.contract_id == prepared.contract.contract_id,
            "prepared_hash": (binding.plan_revision.prepared_mission_sha256 == prepared_hash),
        }
        if not all(gates.values()):
            raise PreparedMissionBindingError("MISSION_LIFECYCLE_SIDECAR_MISMATCH")
        return context_store.lifecycle.import_binding(binding)

    thread = context_store.lifecycle.ensure_thread(prepared.contract.conversation_id)
    if thread.current_plan_revision_id is not None:
        revision = context_store.lifecycle.get_revision(thread.current_plan_revision_id)
        if (
            revision is not None
            and revision.status == "proposed"
            and revision.contract_id == prepared.contract.contract_id
            and revision.prepared_mission_sha256 == prepared_hash
        ):
            return MissionLifecycleBinding(thread=thread, plan_revision=revision)
    return context_store.lifecycle.record_plan_revision(
        conversation_id=prepared.contract.conversation_id,
        contract_id=prepared.contract.contract_id,
        prepared_mission_sha256=prepared_hash,
        source_message_sha256=sha256_json(prepared.intent),
    )


def _binding_gates(
    *,
    prepared: PreparedMission,
    runtime: Px4GazeboRunEvidence,
    route_path: Path,
    clearance_path: Path,
    track_path: Path,
) -> dict[str, bool]:
    return {
        "runtime_route_file_hash_matches_prepared_file": (
            runtime.artifacts.route_sha256 == _file_sha256(route_path)
        ),
        "runtime_track_file_hash_matches_prepared_file": (
            runtime.artifacts.track_sha256 == _file_sha256(track_path)
        ),
        "runtime_clearance_file_hash_matches_prepared_file": (
            runtime.artifacts.clearance_sha256 == _file_sha256(clearance_path)
        ),
        "runtime_semantic_file_hash_matches_contract": (
            runtime.artifacts.semantic_sha256 == prepared.contract.map_semantic_sha256
        ),
        "runtime_vehicle_file_hash_matches_contract": (
            runtime.artifacts.vehicle_sha256 == prepared.contract.vehicle_sha256
        ),
    }


def _complete(
    *,
    prepared: PreparedMission,
    route_path: Path,
    clearance_path: Path,
    track_path: Path,
    route: GraphRoute,
    clearance: RouteClearanceReport,
    track: Px4Track,
    runtime: Px4GazeboRunEvidence,
    offboard_timing: dict[str, Any],
    run_dir: Path,
    completion_provider: ProviderName,
    context_store: ContextStore,
    model_timeout_seconds: float,
    evidence_filename: str,
    result_filename: str,
    checkpoint_decisions: list[RuntimeCheckpointDecision],
    runtime_interruption_decisions: list[RuntimeInterruptionDecision],
    expected_checkpoint_count: int,
) -> SimulationWorkflowResult:
    extensions = runtime_extension_registry(prepared)
    receipt_path = run_dir / "plugin-hook-receipts.jsonl"
    plugin_receipts = list(prepared.plugin_hook_receipts)
    plugin_receipts.extend(
        receipt for decision in checkpoint_decisions for receipt in decision.plugin_hook_receipts
    )
    plugin_receipts.extend(
        receipt
        for decision in runtime_interruption_decisions
        for receipt in decision.plugin_hook_receipts
    )
    binding_gates = _binding_gates(
        prepared=prepared,
        runtime=runtime,
        route_path=route_path,
        clearance_path=clearance_path,
        track_path=track_path,
    )
    chain = EvidenceChain(run_dir / evidence_filename)
    chain.append(
        "workflow.prepared-mission",
        {
            "contract_id": prepared.contract.contract_id,
            "canonical_json_hash_domain": {
                "prepared_mission_sha256": sha256_json(prepared),
                "route_sha256": sha256_json(route),
                "track_sha256": sha256_json(track),
                "clearance_sha256": sha256_json(clearance),
            },
            "file_byte_hash_domain": {
                "route_sha256": _file_sha256(route_path),
                "track_sha256": _file_sha256(track_path),
                "clearance_sha256": _file_sha256(clearance_path),
            },
        },
    )
    chain.append("workflow.runtime", runtime.model_dump(mode="json"))
    for decision in checkpoint_decisions:
        chain.append(
            "model.execution_monitor",
            decision.model_dump(mode="json"),
        )
        context_store.append(
            prepared.contract.conversation_id,
            role="assistant",
            event_type="model.execution_monitor",
            payload=decision.model_dump(mode="json"),
        )
    for decision in runtime_interruption_decisions:
        chain.append("model.runtime_message_classifier", decision.model_dump(mode="json"))
        context_store.append(
            prepared.contract.conversation_id,
            role="assistant",
            event_type="model.runtime_message_classifier",
            payload=decision.model_dump(mode="json"),
        )
    context_store.append(
        prepared.contract.conversation_id,
        role="tool",
        event_type="simulation.runtime",
        payload=runtime.model_dump(mode="json"),
    )

    replacement_decisions = [
        decision
        for decision in runtime_interruption_decisions
        if decision.authorized_action == "hold_for_replan"
    ]
    adoption_dir = run_dir / "runtime-control" / "adoptions"
    adoption_count = len(list(adoption_dir.glob("*.json"))) if adoption_dir.is_dir() else 0
    checkpoint_gate = all(
        decision.continue_authorized and decision.assessment.action == "accept"
        for decision in checkpoint_decisions
    ) and (
        len(checkpoint_decisions) == expected_checkpoint_count
        or (bool(replacement_decisions) and adoption_count == len(replacement_decisions))
    )
    binding_gates["all_required_model_checkpoints_accepted"] = checkpoint_gate
    binding_gates["runtime_replacements_adopted_if_requested"] = adoption_count == len(
        replacement_decisions
    )
    binding_gates["hash_bound_user_confirmation_consumed"] = True
    try:
        runtime_evaluations, runtime_evaluation_receipts = extensions.invoke_multiple(
            "evaluation.runtime-gates",
            "evaluate_runtime",
            prepared=prepared,
            runtime=runtime,
            binding_gates=dict(binding_gates),
            checkpoint_decisions=checkpoint_decisions,
            runtime_interruption_decisions=runtime_interruption_decisions,
            run_dir=run_dir,
        )
        plugin_receipts.extend(runtime_evaluation_receipts)
        runtime_plugin_gates, normalized_runtime_evaluations = require_plugin_acceptance(
            runtime_evaluations,
            gate_prefix="plugin_runtime",
        )
        binding_gates.update(runtime_plugin_gates)
        completion_instructions, completion_prompt_receipts = augment_runtime_prompt(
            extensions,
            role="completion_verifier",
            instructions=COMPLETION_VERIFIER,
        )
        plugin_receipts.extend(completion_prompt_receipts)
    except ExtensionExecutionError as error:
        append_hook_receipts(receipt_path, [error.receipt])
        raise
    append_hook_receipts(
        receipt_path,
        [*runtime_evaluation_receipts, *completion_prompt_receipts],
    )
    deterministic_success = (
        runtime.status == "verified"
        and all(runtime.gates.model_dump().values())
        and all(binding_gates.values())
    )
    port = StructuredModelPort(
        completion_provider, max_attempts=3, timeout_seconds=model_timeout_seconds
    )
    completion = port.call(
        role="completion_verifier",
        output_type=CompletionAssessment,
        instructions=completion_instructions,
        input_artifact={
            "mission_contract": prepared.contract.model_dump(mode="json"),
            "execution_authorization": {
                "contract_confirmation_verified": True,
                "confirmed_contract_id": prepared.contract.contract_id,
                "pre_confirmation_constraints_satisfied": [
                    constraint
                    for constraint in prepared.contract.constraints
                    if constraint in {"plan_only", "do_not_execute"}
                ],
                "semantics": (
                    "The plan was displayed without execution; this run began only after "
                    "the caller confirmed the exact immutable contract ID."
                ),
            },
            "hash_domains": {
                "canonical_json": {
                    "prepared_mission_sha256": sha256_json(prepared),
                    "route_sha256": sha256_json(route),
                    "track_sha256": sha256_json(track),
                    "clearance_sha256": sha256_json(clearance),
                },
                "runtime_file_bytes": {
                    "route_sha256": runtime.artifacts.route_sha256,
                    "track_sha256": runtime.artifacts.track_sha256,
                    "clearance_sha256": runtime.artifacts.clearance_sha256,
                },
            },
            "binding_gates": binding_gates,
            "plugin_runtime_evaluations": normalized_runtime_evaluations,
            "checkpoint_decisions": [
                {
                    "request_sha256": decision.request_sha256,
                    "action": decision.assessment.action,
                    "issue_codes": decision.assessment.issue_codes,
                    "continue_authorized": decision.continue_authorized,
                    "model_output_sha256": decision.model_call.output_sha256,
                }
                for decision in checkpoint_decisions
            ],
            "runtime_interruption_decisions": [
                {
                    "message_sha256": decision.message_sha256,
                    "hold_ack_sha256": decision.hold_ack_sha256,
                    "message_kind": decision.classification.message_kind,
                    "requested_action": decision.classification.requested_action,
                    "authorized_action": decision.authorized_action,
                    "authorization_gates": decision.authorization_gates,
                    "model_output_sha256": decision.model_call.output_sha256,
                }
                for decision in runtime_interruption_decisions
            ],
            "runtime_evidence": runtime.model_dump(mode="json"),
            "offboard_timing": {
                "status": offboard_timing.get("status"),
                "cleanup": offboard_timing.get("cleanup"),
                "track_end_t": offboard_timing.get("track_end_t"),
                "land_confirmed_t": offboard_timing.get("land_confirmed_t"),
            },
            "deterministic_success": deterministic_success,
        },
        context_id=f"{prepared.contract.conversation_id}::completion_verifier",
    )
    try:
        completion_output_receipts = validate_runtime_model_output(
            extensions,
            role="completion_verifier",
            expected_schema=CompletionAssessment.__name__,
            artifact=completion.artifact,
            record=completion.record,
        )
    except ExtensionExecutionError as error:
        append_hook_receipts(receipt_path, [error.receipt])
        raise
    plugin_receipts.extend(completion_output_receipts)
    append_hook_receipts(receipt_path, completion_output_receipts)
    completion_payload = {
        "artifact": completion.artifact.model_dump(mode="json"),
        "record": completion.record.model_dump(mode="json"),
    }
    context_store.append(
        prepared.contract.conversation_id,
        role="assistant",
        event_type="model.completion_verifier",
        payload=completion_payload,
    )
    chain.append("model.completion_verifier", completion_payload)
    exporter_outputs, exporter_receipts = extensions.invoke_multiple(
        "evidence.exporters",
        "export_evidence",
        run_dir=run_dir,
        prepared=prepared,
        runtime=runtime,
        binding_gates=dict(binding_gates),
        plugin_evaluations=normalized_runtime_evaluations,
        completion_assessment=completion.artifact,
    )
    plugin_receipts.extend(exporter_receipts)
    append_hook_receipts(receipt_path, exporter_receipts)
    for receipt in [
        *runtime_evaluation_receipts,
        *completion_prompt_receipts,
        *completion_output_receipts,
        *exporter_receipts,
    ]:
        chain.append("plugin.hook", receipt.model_dump(mode="json"))
    for output in exporter_outputs:
        chain.append("plugin.evidence-export", output)
    head = chain.read()[-1].record_sha256
    result = SimulationWorkflowResult(
        status=("verified" if deterministic_success and completion.artifact.accepted else "failed"),
        contract_id=prepared.contract.contract_id,
        prepared_mission_sha256=sha256_json(prepared),
        runtime_evidence=runtime,
        completion_assessment=completion.artifact,
        completion_model_call=completion.record,
        checkpoint_decisions=checkpoint_decisions,
        runtime_interruption_decisions=runtime_interruption_decisions,
        plugin_hook_receipts=plugin_receipts,
        workflow_evidence_chain_head=head,
    )
    (run_dir / result_filename).write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return result


def execute_prepared_mission(
    *,
    prepared_path: Path,
    confirm_contract_id: str,
    run_dir: Path,
    world_sdf: Path,
    semantic_path: Path,
    vehicle_sdf: Path,
    controller_params_path: Path,
    executor_path: Path,
    px4_root: Path,
    ros_workspace: Path,
    completion_provider: ProviderName,
    context_store: ContextStore,
    model_timeout_seconds: float = 180.0,
    checkpoint_provider: ProviderName | None = None,
    checkpoint_executor_path: Path | None = None,
    checkpoint_timeout_seconds: float = 180.0,
    runtime_interrupt_provider: ProviderName | None = None,
    runtime_hold_timeout_seconds: float = 12.0,
    runtime_decision_timeout_seconds: float = 180.0,
    runtime_replan_hold_seconds: float = 30.0,
    map_graph_path: Path | None = None,
    vehicle_metadata_path: Path | None = None,
) -> SimulationWorkflowResult:
    (
        prepared,
        route_path,
        clearance_path,
        track_path,
        route,
        clearance,
        track,
    ) = _load_package(prepared_path, confirm_contract_id, semantic_path, vehicle_sdf)
    runtime_map_graph: MapAsset | None = None
    runtime_map_catalog = None
    runtime_vehicle: VehicleAsset | None = None
    if runtime_interrupt_provider is not None:
        if map_graph_path is None or vehicle_metadata_path is None:
            raise PreparedMissionBindingError("RUNTIME_REPLAN_ASSETS_REQUIRED")
        runtime_map_graph = MapAsset.model_validate_json(map_graph_path.read_text(encoding="utf-8"))
        runtime_vehicle = VehicleAsset.model_validate_json(
            vehicle_metadata_path.read_text(encoding="utf-8")
        )
        runtime_map_catalog = load_school_map_catalog(semantic_path)
        if sha256_json(runtime_map_graph) != prepared.contract.map_sha256:
            raise PreparedMissionBindingError("RUNTIME_MAP_GRAPH_HASH_MISMATCH")
        if runtime_vehicle.asset_id != prepared.contract.vehicle_asset_id:
            raise PreparedMissionBindingError("RUNTIME_VEHICLE_ID_MISMATCH")
    if runtime_interrupt_provider is not None and (
        checkpoint_provider is None or checkpoint_executor_path is None
    ):
        raise ValueError("runtime interruption requires the checkpoint provider and executor")

    lifecycle = _execution_lifecycle_binding(
        prepared_path=prepared_path, prepared=prepared, context_store=context_store
    )
    thread, plan_revision, execution_id = context_store.lifecycle.confirm_execution(
        conversation_id=prepared.contract.conversation_id,
        plan_revision_id=lifecycle.plan_revision.plan_revision_id,
        contract_id=prepared.contract.contract_id,
        prepared_mission_sha256=sha256_json(prepared),
    )
    checkpoint_decisions: list[RuntimeCheckpointDecision] = []
    runtime_interruption_decisions: list[RuntimeInterruptionDecision] = []
    expected_checkpoint_count = 0
    control_dir = run_dir / "runtime-control"
    runtime_session = None
    if runtime_interrupt_provider is not None:
        try:
            runtime_session = create_runtime_control_session(
                control_dir=control_dir,
                conversation_id=thread.conversation_id,
                mission_id=thread.mission_id,
                plan_revision_id=plan_revision.plan_revision_id,
                contract_id=prepared.contract.contract_id,
                execution_id=execution_id,
                prepared_mission_sha256=sha256_json(prepared),
            )
        except BaseException:
            context_store.lifecycle.set_execution_state(
                conversation_id=prepared.contract.conversation_id,
                execution_id=execution_id,
                state="failed",
            )
            raise

    result: SimulationWorkflowResult | None = None
    try:
        if checkpoint_provider is not None:
            if checkpoint_executor_path is None:
                raise ValueError("checkpoint_executor_path is required with checkpoint_provider")
            checkpoint_contract = checkpoint_contract_for(prepared)
            expected_checkpoint_count = len(checkpoint_contract.checkpoints)
            with tempfile.TemporaryDirectory(prefix="dronedream-checkpoints-") as temporary:
                checkpoint_path = Path(temporary) / "runtime-checkpoints.json"
                checkpoint_path.write_text(
                    checkpoint_contract.model_dump_json(indent=2) + "\n",
                    encoding="utf-8",
                )
                checkpoint_coordinator = CheckpointCoordinator(
                    prepared=prepared,
                    run_dir=run_dir,
                    provider=checkpoint_provider,
                    abort_file=run_dir / "live_abort.request.json",
                    model_timeout_seconds=model_timeout_seconds,
                )
                interruption_coordinator = (
                    RuntimeInterruptionCoordinator(
                        prepared=prepared,
                        session=runtime_session,
                        control_dir=control_dir,
                        provider=runtime_interrupt_provider,
                        abort_file=run_dir / "live_abort.request.json",
                        lifecycle_db_path=context_store.path,
                        model_timeout_seconds=model_timeout_seconds,
                        map_graph=runtime_map_graph,
                        map_catalog=runtime_map_catalog,
                        semantic_path=semantic_path,
                        vehicle=runtime_vehicle,
                    )
                    if runtime_session is not None and runtime_interrupt_provider is not None
                    else None
                )
                checkpoint_coordinator.start()
                if interruption_coordinator is not None:
                    interruption_coordinator.start()
                extra_args = [
                    "--base-executor",
                    str(executor_path),
                    "--checkpoint-contract",
                    str(checkpoint_path),
                    "--checkpoint-timeout-seconds",
                    f"{checkpoint_timeout_seconds:g}",
                ]
                if runtime_session is not None:
                    extra_args.extend(
                        [
                            "--runtime-control-dir",
                            str(control_dir),
                            "--runtime-hold-timeout-seconds",
                            f"{runtime_hold_timeout_seconds:g}",
                            "--runtime-decision-timeout-seconds",
                            f"{runtime_decision_timeout_seconds:g}",
                            "--runtime-replan-hold-seconds",
                            f"{runtime_replan_hold_seconds:g}",
                            "--semantic",
                            str(semantic_path),
                            "--vehicle-metadata",
                            str(vehicle_metadata_path),
                        ]
                    )
                try:
                    raw_runtime = run_px4_gazebo_track(
                        run_dir=run_dir,
                        world_sdf=world_sdf,
                        semantic_path=semantic_path,
                        vehicle_sdf=vehicle_sdf,
                        route_path=route_path,
                        track_path=track_path,
                        clearance_path=clearance_path,
                        controller_params_path=controller_params_path,
                        px4_root=px4_root,
                        executor_path=checkpoint_executor_path,
                        ros_workspace=ros_workspace,
                        contract_id=prepared.contract.contract_id,
                        executor_extra_args=extra_args,
                    )
                finally:
                    checkpoint_coordinator.stop(timeout_seconds=model_timeout_seconds + 10.0)
                    if interruption_coordinator is not None:
                        interruption_coordinator.stop(timeout_seconds=model_timeout_seconds + 10.0)
                if checkpoint_coordinator.error is not None:
                    raise RuntimeError("checkpoint coordinator failed") from (
                        checkpoint_coordinator.error
                    )
                checkpoint_decisions = list(checkpoint_coordinator.decisions)
                if interruption_coordinator is not None:
                    if interruption_coordinator.error is not None:
                        raise RuntimeError("runtime interruption coordinator failed") from (
                            interruption_coordinator.error
                        )
                    runtime_interruption_decisions = list(interruption_coordinator.decisions)
        else:
            raw_runtime = run_px4_gazebo_track(
                run_dir=run_dir,
                world_sdf=world_sdf,
                semantic_path=semantic_path,
                vehicle_sdf=vehicle_sdf,
                route_path=route_path,
                track_path=track_path,
                clearance_path=clearance_path,
                controller_params_path=controller_params_path,
                px4_root=px4_root,
                executor_path=executor_path,
                ros_workspace=ros_workspace,
                contract_id=prepared.contract.contract_id,
            )
        runtime = Px4GazeboRunEvidence.model_validate(raw_runtime)
        offboard_timing = json.loads((run_dir / "offboard_timing.json").read_text(encoding="utf-8"))
        result = _complete(
            prepared=prepared,
            route_path=route_path,
            clearance_path=clearance_path,
            track_path=track_path,
            route=route,
            clearance=clearance,
            track=track,
            runtime=runtime,
            offboard_timing=offboard_timing,
            run_dir=run_dir,
            completion_provider=completion_provider,
            context_store=context_store,
            model_timeout_seconds=model_timeout_seconds,
            evidence_filename="workflow-evidence.jsonl",
            result_filename="workflow-result.json",
            checkpoint_decisions=checkpoint_decisions,
            runtime_interruption_decisions=runtime_interruption_decisions,
            expected_checkpoint_count=expected_checkpoint_count,
        )
        context_store.lifecycle.set_execution_state(
            conversation_id=prepared.contract.conversation_id,
            execution_id=execution_id,
            state="completed" if result.status == "verified" else "failed",
        )
        return result
    except BaseException:
        current = context_store.lifecycle.get_thread(prepared.contract.conversation_id)
        if current is not None and current.active_execution_id == execution_id:
            context_store.lifecycle.set_execution_state(
                conversation_id=prepared.contract.conversation_id,
                execution_id=execution_id,
                state="failed",
            )
        raise
    finally:
        if runtime_session is not None:
            close_runtime_control_session(control_dir)


def reverify_prepared_run(
    *,
    prepared_path: Path,
    confirm_contract_id: str,
    run_dir: Path,
    semantic_path: Path,
    vehicle_sdf: Path,
    completion_provider: ProviderName,
    context_store: ContextStore,
    model_timeout_seconds: float = 180.0,
) -> SimulationWorkflowResult:
    """Re-run only completion review over an immutable finished simulation run."""

    (
        prepared,
        route_path,
        clearance_path,
        track_path,
        route,
        clearance,
        track,
    ) = _load_package(prepared_path, confirm_contract_id, semantic_path, vehicle_sdf)
    raw_runtime = json.loads((run_dir / "mission_evidence.json").read_text(encoding="utf-8"))
    offboard_timing = json.loads((run_dir / "offboard_timing.json").read_text(encoding="utf-8"))
    landing_state = offboard_timing.get("cleanup", {}).get("landing_observation", {}).get("state")
    raw_runtime["gates"]["landing_confirmed"] = (
        str(offboard_timing.get("cleanup", {}).get("land", "")).startswith("confirmed_on_ground")
        and landing_state == "ON_GROUND"
    )
    raw_runtime["measurements"]["landing_state"] = landing_state
    runtime = Px4GazeboRunEvidence.model_validate(raw_runtime)
    prior_result_path = run_dir / "workflow-result.json"
    if not prior_result_path.is_file():
        raise PreparedMissionBindingError("ORIGINAL_WORKFLOW_RESULT_MISSING")
    prior_result = SimulationWorkflowResult.model_validate_json(
        prior_result_path.read_text(encoding="utf-8")
    )
    if prior_result.contract_id != prepared.contract.contract_id:
        raise PreparedMissionBindingError("ORIGINAL_WORKFLOW_CONTRACT_MISMATCH")
    if prior_result.prepared_mission_sha256 != sha256_json(prepared):
        raise PreparedMissionBindingError("ORIGINAL_WORKFLOW_PREPARED_HASH_MISMATCH")
    for item in runtime.artifacts.px4_ulogs:
        ulog_path = (run_dir / item.path).resolve()
        try:
            ulog_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise PreparedMissionBindingError("PX4_ULOG_PATH_ESCAPES_RUN") from exc
        if (
            not ulog_path.is_file()
            or ulog_path.stat().st_size != item.size_bytes
            or _file_sha256(ulog_path) != item.sha256
        ):
            raise PreparedMissionBindingError("PX4_ULOG_BINDING_MISMATCH")
    return _complete(
        prepared=prepared,
        route_path=route_path,
        clearance_path=clearance_path,
        track_path=track_path,
        route=route,
        clearance=clearance,
        track=track,
        runtime=runtime,
        offboard_timing=offboard_timing,
        run_dir=run_dir,
        completion_provider=completion_provider,
        context_store=context_store,
        model_timeout_seconds=model_timeout_seconds,
        evidence_filename="workflow-evidence.jsonl",
        result_filename="workflow-result.json",
        checkpoint_decisions=prior_result.checkpoint_decisions,
        runtime_interruption_decisions=prior_result.runtime_interruption_decisions,
        expected_checkpoint_count=len(checkpoint_contract_for(prepared).checkpoints),
    )
