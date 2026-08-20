"""Runtime message ingress, structured classification, and fail-closed authorization."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import (
    MapAsset,
    MapCatalog,
    PreparedMission,
    RuntimeAmendmentDirective,
    RuntimeAuthorizedCommand,
    RuntimeCommandAdoption,
    RuntimeControlSession,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeMessageClassification,
    RuntimeOperatorTakeoverAdoption,
    RuntimeOperatorTakeoverGrant,
    RuntimeReplacementTrack,
    RuntimeUserMessage,
    VehicleAsset,
)
from .extensions import ExtensionExecutionError
from .hashing import sha256_json
from .model_port import ProviderName, StructuredModelPort
from .prompts import RUNTIME_MESSAGE_CLASSIFIER
from .runtime_commands import RuntimeCommandError, build_runtime_command
from .runtime_plugins import (
    append_hook_receipts,
    augment_runtime_prompt,
    runtime_extension_registry,
    validate_runtime_model_output,
)
from .runtime_replan import (
    RuntimeReplanError,
    build_runtime_coverage_replacement,
    build_runtime_replacement,
    build_runtime_speed_replacement,
)


class RuntimeMessageRejected(RuntimeError):
    """Runtime ingress rejected an unbound or no-longer-actionable message."""


def _runtime_adoption_gates(
    *,
    adoption: dict[str, object],
    replacement: RuntimeReplacementTrack,
    session: RuntimeControlSession,
) -> dict[str, bool]:
    return {
        "execution": adoption.get("execution_id") == session.execution_id,
        "message": adoption.get("message_id") == replacement.message_id,
        "replacement_sequence": (
            adoption.get("replacement_sequence") == replacement.replacement_sequence
        ),
        "replacement_hash": adoption.get("replacement_sha256") == sha256_json(replacement),
        "track_hash": adoption.get("track_sha256") == sha256_json(replacement.track),
        "replacement_execution": replacement.execution_id == session.execution_id,
        "replacement_gates": all(replacement.deterministic_gates.values()),
    }


def _runtime_command_adoption_gates(
    *,
    adoption: RuntimeCommandAdoption,
    command: RuntimeAuthorizedCommand,
    session: RuntimeControlSession,
) -> dict[str, bool]:
    return {
        "execution": adoption.execution_id == session.execution_id,
        "message": adoption.message_id == command.message_id,
        "action": adoption.action == command.action,
        "command_hash": adoption.command_sha256 == sha256_json(command),
        "command_execution": command.execution_id == session.execution_id,
        "command_gates": all(command.deterministic_gates.values()),
        "execution_success": adoption.success,
    }


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


def create_runtime_control_session(
    *,
    control_dir: Path,
    conversation_id: str,
    mission_id: str,
    plan_revision_id: str,
    contract_id: str,
    execution_id: str,
    prepared_mission_sha256: str,
) -> RuntimeControlSession:
    session_path = control_dir / "session.json"
    if session_path.exists():
        raise FileExistsError(f"runtime control session already exists: {session_path}")
    session = RuntimeControlSession(
        conversation_id=conversation_id,
        mission_id=mission_id,
        plan_revision_id=plan_revision_id,
        contract_id=contract_id,
        execution_id=execution_id,
        prepared_mission_sha256=prepared_mission_sha256,
        created_at=datetime.now(UTC),
    )
    for name in (
        "inbox",
        "claimed",
        "acks",
        "decisions",
        "processed",
        "replacements",
        "replan-failures",
        "commands",
        "command-results",
        "command-failures",
        "adoptions",
        "takeover-grants",
        "takeover-adoptions",
        "operator-commands",
        "processed-operator-commands",
        "takeover-evidence",
        "follow",
    ):
        (control_dir / name).mkdir(parents=True, exist_ok=True)
    _atomic_json(session_path, session)
    _atomic_json(
        control_dir / "side-effects.state.json",
        {
            "enabled": True,
            "execution_id": execution_id,
            "reason": "active confirmed plan",
        },
    )
    return session


def close_runtime_control_session(control_dir: Path) -> RuntimeControlSession:
    path = control_dir / "session.json"
    session = RuntimeControlSession.model_validate_json(path.read_text(encoding="utf-8"))
    closed = session.model_copy(update={"state": "closed"})
    _atomic_json(path, closed)
    return closed


def submit_runtime_message(*, control_dir: Path, text: str) -> RuntimeUserMessage:
    """Atomically enqueue one message, bound to the exact active execution."""

    session_path = control_dir / "session.json"
    if not session_path.is_file():
        raise RuntimeMessageRejected("RUNTIME_CONTROL_SESSION_NOT_FOUND")
    session = RuntimeControlSession.model_validate_json(session_path.read_text(encoding="utf-8"))
    if session.state != "accepting":
        raise RuntimeMessageRejected("RUNTIME_CONTROL_SESSION_CLOSED")
    phase_path = control_dir.parent / "runtime-phase.json"
    if phase_path.is_file():
        phase = json.loads(phase_path.read_text(encoding="utf-8")).get("phase")
        if phase in {"LANDING", "LANDED", "COMPLETE", "FAILED"}:
            raise RuntimeMessageRejected(f"RUNTIME_MESSAGE_TOO_LATE:{phase}")
    message = RuntimeUserMessage(
        message_id=f"runtime-msg-{uuid4().hex}",
        conversation_id=session.conversation_id,
        mission_id=session.mission_id,
        plan_revision_id=session.plan_revision_id,
        contract_id=session.contract_id,
        execution_id=session.execution_id,
        text=text,
        submitted_at=datetime.now(UTC),
    )
    _atomic_json(control_dir / "inbox" / f"{message.message_id}.json", message)
    return message


_EMERGENCY_TOKENS = (
    "紧急",
    "停止",
    "停下",
    "降落",
    "立即停",
    "abort",
    "emergency",
    "stop",
    "land now",
)
_AMENDMENT_TOKENS = (
    "改到",
    "改去",
    "改道",
    "改变目的地",
    "不是",
    "不要继续去",
    "换成",
    "换到",
    "另一个",
    "change destination",
    "instead",
    "reroute",
)


def authorize_runtime_action(
    *,
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    classification: RuntimeMessageClassification,
) -> tuple[str, dict[str, bool], str]:
    """The model classifies; deterministic code alone authorizes the next state."""

    normalized = message.text.casefold()
    emergency_override = any(token in normalized for token in _EMERGENCY_TOKENS)
    amendment_override = any(token in normalized for token in _AMENDMENT_TOKENS)
    gates = {
        "message_hash_matches_ack": (acknowledgement.message_sha256 == sha256_json(message)),
        "message_id_matches_ack": message.message_id == acknowledgement.message_id,
        "execution_id_matches_ack": (message.execution_id == acknowledgement.execution_id),
        "side_effects_inhibited": acknowledgement.side_effects_inhibited,
        "hold_deterministic_gates_passed": all(acknowledgement.deterministic_gates.values()),
    }
    if not all(gates.values()):
        return "land", gates, "Hold acknowledgement failed a deterministic safety gate."
    if emergency_override or classification.message_kind == "emergency_stop":
        return "land", gates, "Emergency wording or classification forces controlled landing."
    if classification.requested_action == "safe_land":
        return "land", gates, "A safe-land amendment is authorized only as controlled landing."
    if classification.requested_action == "operator_takeover":
        return "hold", gates, "Operator takeover requires a separate authenticated control grant."
    if classification.requested_action in {
        "camera_control",
        "payload_control",
        "set_avoidance",
    }:
        return (
            "apply_command",
            gates,
            "A bounded peripheral or flight-policy command requires code validation and readback.",
        )
    if classification.requested_action == "pause" and not amendment_override:
        return "hold", gates, "Pause keeps the aircraft in deterministic stable hold."
    if (
        amendment_override
        or classification.requires_plan_revision
        or classification.message_kind in {"mission_amendment", "motion_adjustment"}
        or classification.requested_action in {"replan", "adjust_motion"}
    ):
        return (
            "hold_for_replan",
            gates,
            "The old plan is superseded; continuation requires a new code-validated revision.",
        )
    if (
        classification.message_kind == "informational"
        and classification.requested_action == "resume"
    ):
        return "resume_original", gates, "Informational message does not alter the plan."
    return "hold_for_replan", gates, "Ambiguous runtime intent cannot resume the old plan."


class RuntimeInterruptionCoordinator:
    """Waits for stable-hold evidence before making any real model call."""

    def __init__(
        self,
        *,
        prepared: PreparedMission,
        session: RuntimeControlSession,
        control_dir: Path,
        provider: ProviderName,
        abort_file: Path,
        lifecycle_db_path: Path,
        model_timeout_seconds: float,
        map_graph: MapAsset,
        map_catalog: MapCatalog,
        semantic_path: Path,
        vehicle: VehicleAsset,
    ) -> None:
        self.prepared = prepared
        self.session = session
        self.control_dir = control_dir
        self.abort_file = abort_file
        self.lifecycle_db_path = lifecycle_db_path
        self.map_graph = map_graph
        self.map_catalog = map_catalog
        self.semantic_path = semantic_path
        self.vehicle = vehicle
        self.port = StructuredModelPort(
            provider, max_attempts=3, timeout_seconds=model_timeout_seconds
        )
        self.extensions = runtime_extension_registry(prepared)
        self.receipt_path = control_dir.parent / "plugin-hook-receipts.jsonl"
        self.adoption_timeout_seconds = min(model_timeout_seconds, 30.0)
        self.decisions: list[RuntimeInterruptionDecision] = []
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="runtime-interruption-coordinator", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout_seconds: float) -> None:
        self._stop.set()
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise TimeoutError("runtime interruption coordinator did not stop")

    def _request_abort(self, reason: str) -> None:
        _atomic_json(
            self.abort_file,
            {"reason": reason, "requested_at": datetime.now(UTC).isoformat()},
        )

    def _run(self) -> None:
        from .context import ContextStore

        processed: set[str] = set()
        resumed_adoptions: set[str] = set()
        lifecycle_context = ContextStore(self.lifecycle_db_path)
        try:
            while not self._stop.wait(0.05):
                for adoption_path in sorted((self.control_dir / "adoptions").glob("*.json")):
                    message_id = adoption_path.stem
                    if message_id in resumed_adoptions:
                        continue
                    replacement_path = self.control_dir / "replacements" / f"{message_id}.json"
                    command_path = self.control_dir / "commands" / f"{message_id}.json"
                    if replacement_path.is_file():
                        adoption_value = json.loads(adoption_path.read_text(encoding="utf-8"))
                        if not isinstance(adoption_value, dict):
                            raise RuntimeMessageRejected("RUNTIME_ADOPTION_INVALID")
                        replacement = RuntimeReplacementTrack.model_validate_json(
                            replacement_path.read_text(encoding="utf-8")
                        )
                        adoption_gates = _runtime_adoption_gates(
                            adoption=adoption_value,
                            replacement=replacement,
                            session=self.session,
                        )
                    elif command_path.is_file():
                        adoption = RuntimeCommandAdoption.model_validate_json(
                            adoption_path.read_text(encoding="utf-8")
                        )
                        command = RuntimeAuthorizedCommand.model_validate_json(
                            command_path.read_text(encoding="utf-8")
                        )
                        adoption_gates = _runtime_command_adoption_gates(
                            adoption=adoption,
                            command=command,
                            session=self.session,
                        )
                    else:
                        continue
                    if not all(adoption_gates.values()):
                        failed = ",".join(
                            name for name, accepted in adoption_gates.items() if not accepted
                        )
                        raise RuntimeMessageRejected(f"RUNTIME_ADOPTION_REJECTED:{failed}")
                    lifecycle_context.lifecycle.set_execution_state(
                        conversation_id=self.session.conversation_id,
                        execution_id=self.session.execution_id,
                        state="executing",
                    )
                    resumed_adoptions.add(message_id)
                for ack_path in sorted((self.control_dir / "acks").glob("*.json")):
                    message_id = ack_path.stem
                    if message_id in processed:
                        continue
                    message_path = self.control_dir / "claimed" / f"{message_id}.json"
                    if not message_path.is_file():
                        continue
                    message = RuntimeUserMessage.model_validate_json(
                        message_path.read_text(encoding="utf-8")
                    )
                    acknowledgement = RuntimeHoldAcknowledgement.model_validate_json(
                        ack_path.read_text(encoding="utf-8")
                    )
                    identity_gates = {
                        "conversation": message.conversation_id == self.session.conversation_id,
                        "mission": message.mission_id == self.session.mission_id,
                        "plan_revision": (
                            message.plan_revision_id == self.session.plan_revision_id
                        ),
                        "contract": message.contract_id == self.session.contract_id,
                        "execution": message.execution_id == self.session.execution_id,
                    }
                    if not all(identity_gates.values()):
                        raise RuntimeMessageRejected("RUNTIME_MESSAGE_SESSION_BINDING_MISMATCH")
                    lifecycle_context.lifecycle.set_execution_state(
                        conversation_id=self.session.conversation_id,
                        execution_id=self.session.execution_id,
                        state="holding",
                    )
                    try:
                        instructions, prompt_receipts = augment_runtime_prompt(
                            self.extensions,
                            role="runtime_message_classifier",
                            instructions=RUNTIME_MESSAGE_CLASSIFIER,
                        )
                    except ExtensionExecutionError as error:
                        append_hook_receipts(self.receipt_path, [error.receipt])
                        raise
                    append_hook_receipts(self.receipt_path, prompt_receipts)
                    result = self.port.call(
                        role="runtime_message_classifier",
                        output_type=RuntimeMessageClassification,
                        instructions=instructions,
                        input_artifact={
                            "runtime_user_message": message.model_dump(mode="json"),
                            "stable_hold_acknowledgement": acknowledgement.model_dump(mode="json"),
                            "mission_contract": self.prepared.contract.model_dump(mode="json"),
                            "current_task_graph": self.prepared.task_graph.model_dump(mode="json"),
                            "current_plan_revision": self.prepared.plan.revision,
                            "immutable_rules": [
                                "The old plan is frozen before this model call.",
                                "The model has no actuator or continuation authority.",
                                "A destination or motion change requires a new plan revision.",
                            ],
                        },
                        context_id=(f"{self.session.conversation_id}::runtime_message_classifier"),
                    )
                    try:
                        output_guard_receipts = validate_runtime_model_output(
                            self.extensions,
                            role="runtime_message_classifier",
                            expected_schema=RuntimeMessageClassification.__name__,
                            artifact=result.artifact,
                            record=result.record,
                        )
                    except ExtensionExecutionError as error:
                        append_hook_receipts(self.receipt_path, [error.receipt])
                        raise
                    append_hook_receipts(self.receipt_path, output_guard_receipts)
                    try:
                        classified_value, classification_receipts = self.extensions.invoke_pipeline(
                            "runtime.amendment-classifier",
                            "classify_amendment",
                            result.artifact.model_dump(mode="json"),
                            message=message,
                            prepared=self.prepared,
                        )
                        classification = RuntimeMessageClassification.model_validate(
                            classified_value
                        )
                        directive_value, directive_receipts = self.extensions.invoke_single(
                            "runtime.amendment-policy",
                            "apply_amendment",
                            required=True,
                            classification=classification,
                            message=message,
                            acknowledgement=acknowledgement,
                            prepared=self.prepared,
                        )
                        directive = RuntimeAmendmentDirective.model_validate(directive_value)
                    except ExtensionExecutionError as error:
                        append_hook_receipts(self.receipt_path, [error.receipt])
                        raise
                    append_hook_receipts(
                        self.receipt_path, [*classification_receipts, *directive_receipts]
                    )
                    action, authorization_gates, reason = authorize_runtime_action(
                        message=message,
                        acknowledgement=acknowledgement,
                        classification=classification,
                    )
                    if directive.issue_codes:
                        action = "hold"
                        reason = "Runtime amendment parameters failed deterministic validation."
                    decision = RuntimeInterruptionDecision(
                        message_sha256=sha256_json(message),
                        hold_ack_sha256=sha256_json(acknowledgement),
                        classification=classification,
                        model_call=result.record,
                        authorized_action=action,
                        authorization_gates={**identity_gates, **authorization_gates},
                        decision_reason=reason,
                        plugin_hook_receipts=[
                            *prompt_receipts,
                            *output_guard_receipts,
                            *classification_receipts,
                            *directive_receipts,
                        ],
                        amendment_directive=directive,
                    )
                    self.decisions.append(decision)
                    _atomic_json(self.control_dir / "decisions" / f"{message_id}.json", decision)
                    if decision.authorized_action == "apply_command":
                        try:
                            command = build_runtime_command(
                                message=message,
                                acknowledgement=acknowledgement,
                                decision=decision,
                            )
                            _atomic_json(
                                self.control_dir / "commands" / f"{message_id}.json",
                                command,
                            )
                            adoption_path = self.control_dir / "adoptions" / f"{message_id}.json"
                            adoption_deadline = time.monotonic() + self.adoption_timeout_seconds
                            while not self._stop.wait(0.05):
                                if adoption_path.is_file():
                                    adoption = RuntimeCommandAdoption.model_validate_json(
                                        adoption_path.read_text(encoding="utf-8")
                                    )
                                    adoption_gates = _runtime_command_adoption_gates(
                                        adoption=adoption,
                                        command=command,
                                        session=self.session,
                                    )
                                    if not all(adoption_gates.values()):
                                        failed = ",".join(
                                            name
                                            for name, accepted in adoption_gates.items()
                                            if not accepted
                                        )
                                        raise RuntimeMessageRejected(
                                            f"RUNTIME_COMMAND_ADOPTION_REJECTED:{failed}"
                                        )
                                    lifecycle_context.lifecycle.set_execution_state(
                                        conversation_id=self.session.conversation_id,
                                        execution_id=self.session.execution_id,
                                        state="executing",
                                    )
                                    resumed_adoptions.add(message_id)
                                    break
                                if time.monotonic() >= adoption_deadline:
                                    raise RuntimeMessageRejected("RUNTIME_COMMAND_ADOPTION_TIMEOUT")
                        except RuntimeCommandError as exc:
                            _atomic_json(
                                self.control_dir / "command-failures" / f"{message_id}.json",
                                {
                                    "message_id": message_id,
                                    "decision_sha256": sha256_json(decision),
                                    "reason": str(exc),
                                    "failed_at": datetime.now(UTC).isoformat(),
                                },
                            )
                    if decision.authorized_action == "hold_for_replan":
                        active_track_path = self.control_dir / "active-track.json"
                        prior_track = self.prepared.px4_track
                        active_target_node = self.prepared.contract.target_node
                        active_return_node = self.prepared.contract.return_node
                        prior_track_sha256 = sha256_json(prior_track)
                        replacement_sequence = 1
                        if active_track_path.is_file():
                            active_track = json.loads(active_track_path.read_text(encoding="utf-8"))
                            if active_track.get("execution_id") != self.session.execution_id:
                                raise RuntimeMessageRejected(
                                    "RUNTIME_ACTIVE_TRACK_EXECUTION_MISMATCH"
                                )
                            prior_track_sha256 = str(active_track["track_sha256"])
                            replacement_sequence = int(active_track["replacement_sequence"]) + 1
                            previous_message_id = str(active_track.get("message_id", ""))
                            previous_path = (
                                self.control_dir / "replacements" / f"{previous_message_id}.json"
                            )
                            if not previous_path.is_file():
                                raise RuntimeMessageRejected(
                                    "RUNTIME_ACTIVE_TRACK_ARTIFACT_MISSING"
                                )
                            previous = RuntimeReplacementTrack.model_validate_json(
                                previous_path.read_text(encoding="utf-8")
                            )
                            if sha256_json(previous.track) != prior_track_sha256:
                                raise RuntimeMessageRejected("RUNTIME_ACTIVE_TRACK_HASH_MISMATCH")
                            prior_track = previous.track
                            active_target_node = previous.target_node
                            active_return_node = previous.return_node
                        try:
                            if decision.classification.requested_action == "set_speed":
                                builder = build_runtime_speed_replacement
                            elif decision.classification.requested_action == "set_coverage":
                                builder = build_runtime_coverage_replacement
                            else:
                                builder = build_runtime_replacement
                            common = dict(
                                message=message,
                                acknowledgement=acknowledgement,
                                decision=decision,
                                replacement_sequence=replacement_sequence,
                                prior_track_sha256=prior_track_sha256,
                                prior_track=prior_track,
                                graph=self.map_graph,
                                semantic_path=self.semantic_path,
                                vehicle=self.vehicle,
                                expected_map_sha256=self.prepared.contract.map_sha256,
                                expected_semantic_sha256=(
                                    self.prepared.contract.map_semantic_sha256
                                ),
                                expected_vehicle_asset_id=(self.prepared.contract.vehicle_asset_id),
                                plugin_snapshot=self.prepared.plugin_snapshot,
                            )
                            if builder in {
                                build_runtime_replacement,
                                build_runtime_coverage_replacement,
                            }:
                                common.update(
                                    catalog=self.map_catalog,
                                    return_node=active_return_node,
                                )
                            if builder is build_runtime_replacement:
                                common["active_target_node"] = active_target_node
                            replacement = builder(**common)
                            _atomic_json(
                                self.control_dir / "replacements" / f"{message_id}.json",
                                replacement,
                            )
                            # The executor adopts replacement tracks asynchronously.  Do not
                            # leave the durable task lifecycle in ``holding`` until mission
                            # completion: wait for the executor's hash-bound adoption receipt,
                            # validate it, and resume the lifecycle in this same message flow.
                            # The outer adoption watcher remains as a recovery path for receipts
                            # that predate coordinator startup.
                            adoption_path = self.control_dir / "adoptions" / f"{message_id}.json"
                            adoption_deadline = time.monotonic() + self.adoption_timeout_seconds
                            while not self._stop.wait(0.05):
                                if adoption_path.is_file():
                                    adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
                                    if not isinstance(adoption, dict):
                                        raise RuntimeMessageRejected("RUNTIME_ADOPTION_INVALID")
                                    adoption_gates = _runtime_adoption_gates(
                                        adoption=adoption,
                                        replacement=replacement,
                                        session=self.session,
                                    )
                                    if not all(adoption_gates.values()):
                                        failed = ",".join(
                                            name
                                            for name, accepted in adoption_gates.items()
                                            if not accepted
                                        )
                                        raise RuntimeMessageRejected(
                                            f"RUNTIME_ADOPTION_REJECTED:{failed}"
                                        )
                                    lifecycle_context.lifecycle.set_execution_state(
                                        conversation_id=self.session.conversation_id,
                                        execution_id=self.session.execution_id,
                                        state="executing",
                                    )
                                    resumed_adoptions.add(message_id)
                                    break
                                if time.monotonic() >= adoption_deadline:
                                    raise RuntimeMessageRejected("RUNTIME_ADOPTION_TIMEOUT")
                        except RuntimeReplanError as exc:
                            _atomic_json(
                                self.control_dir / "replan-failures" / f"{message_id}.json",
                                {
                                    "message_id": message_id,
                                    "decision_sha256": sha256_json(decision),
                                    "reason": str(exc),
                                    "failed_at": datetime.now(UTC).isoformat(),
                                },
                            )
                    if (
                        decision.authorized_action == "hold"
                        and decision.classification.requested_action == "operator_takeover"
                    ):
                        adoption_path = (
                            self.control_dir / "takeover-adoptions" / f"{message_id}.json"
                        )
                        adoption_deadline = time.monotonic() + self.adoption_timeout_seconds
                        while not self._stop.wait(0.05):
                            if adoption_path.is_file():
                                adoption = RuntimeOperatorTakeoverAdoption.model_validate_json(
                                    adoption_path.read_text(encoding="utf-8")
                                )
                                grant_path = (
                                    self.control_dir / "takeover-grants" / f"{message_id}.json"
                                )
                                if not grant_path.is_file():
                                    raise RuntimeMessageRejected(
                                        "RUNTIME_TAKEOVER_GRANT_ARTIFACT_MISSING"
                                    )
                                grant = RuntimeOperatorTakeoverGrant.model_validate_json(
                                    grant_path.read_text(encoding="utf-8")
                                )
                                gates = {
                                    "message_id": adoption.message_id == message_id,
                                    "execution_id": (
                                        adoption.execution_id == self.session.execution_id
                                    ),
                                    "grant_hash": (adoption.grant_sha256 == sha256_json(grant)),
                                }
                                if not all(gates.values()):
                                    failed = ",".join(
                                        name for name, accepted in gates.items() if not accepted
                                    )
                                    raise RuntimeMessageRejected(
                                        f"RUNTIME_TAKEOVER_ADOPTION_REJECTED:{failed}"
                                    )
                                lifecycle_context.lifecycle.set_execution_state(
                                    conversation_id=self.session.conversation_id,
                                    execution_id=self.session.execution_id,
                                    state="executing",
                                )
                                resumed_adoptions.add(message_id)
                                break
                            if time.monotonic() >= adoption_deadline:
                                raise RuntimeMessageRejected("RUNTIME_TAKEOVER_ADOPTION_TIMEOUT")
                    if decision.authorized_action == "resume_original":
                        lifecycle_context.lifecycle.set_execution_state(
                            conversation_id=self.session.conversation_id,
                            execution_id=self.session.execution_id,
                            state="executing",
                        )
                    elif decision.authorized_action == "land":
                        lifecycle_context.lifecycle.set_execution_state(
                            conversation_id=self.session.conversation_id,
                            execution_id=self.session.execution_id,
                            state="landing",
                        )
                    processed.add(message_id)
        except BaseException as exc:
            self.error = exc
            self._request_abort(f"RUNTIME_INTERRUPTION_COORDINATOR_FAILURE_{type(exc).__name__}")
        finally:
            lifecycle_context.close()
            time.sleep(0.05)
