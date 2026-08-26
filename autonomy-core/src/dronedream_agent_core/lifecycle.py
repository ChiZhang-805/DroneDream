"""Transactional task-thread, plan-revision, and execution identity state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from .contracts import MissionLifecycleBinding, PlanRevisionRecord, TaskThread


class LifecycleTransitionError(RuntimeError):
    """A request attempted an invalid task lifecycle transition."""


def _now() -> datetime:
    return datetime.now(UTC)


class MissionLifecycleStore:
    """Uses the ContextStore database connection but keeps lifecycle writes atomic."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_threads (
              conversation_id TEXT PRIMARY KEY,
              mission_id TEXT NOT NULL UNIQUE,
              thread_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_revisions (
              plan_revision_id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              record_json TEXT NOT NULL,
              UNIQUE (conversation_id, revision),
              FOREIGN KEY (conversation_id) REFERENCES task_threads(conversation_id)
            );
            """
        )
        self._connection.commit()

    def _begin(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def _thread(self, conversation_id: str) -> TaskThread | None:
        row = self._connection.execute(
            "SELECT thread_json FROM task_threads WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return TaskThread.model_validate_json(row[0]) if row else None

    def _revision(self, plan_revision_id: str) -> PlanRevisionRecord | None:
        row = self._connection.execute(
            "SELECT record_json FROM plan_revisions WHERE plan_revision_id = ?",
            (plan_revision_id,),
        ).fetchone()
        return PlanRevisionRecord.model_validate_json(row[0]) if row else None

    def get_thread(self, conversation_id: str) -> TaskThread | None:
        return self._thread(conversation_id)

    def get_revision(self, plan_revision_id: str) -> PlanRevisionRecord | None:
        return self._revision(plan_revision_id)

    def ensure_thread(self, conversation_id: str) -> TaskThread:
        self._begin()
        try:
            existing = self._thread(conversation_id)
            if existing is not None:
                self._connection.commit()
                return existing
            now = _now()
            thread = TaskThread(
                conversation_id=conversation_id,
                mission_id=f"mission-{uuid4().hex}",
                state="planning",
                created_at=now,
                updated_at=now,
            )
            self._connection.execute(
                "INSERT INTO task_threads(conversation_id, mission_id, thread_json) "
                "VALUES (?, ?, ?)",
                (conversation_id, thread.mission_id, thread.model_dump_json()),
            )
            self._connection.commit()
            return thread
        except BaseException:
            self._connection.rollback()
            raise

    def record_plan_revision(
        self,
        *,
        conversation_id: str,
        contract_id: str,
        prepared_mission_sha256: str,
        source_message_sha256: str,
    ) -> MissionLifecycleBinding:
        self._begin()
        try:
            thread = self._thread(conversation_id)
            if thread is None:
                now = _now()
                thread = TaskThread(
                    conversation_id=conversation_id,
                    mission_id=f"mission-{uuid4().hex}",
                    state="planning",
                    created_at=now,
                    updated_at=now,
                )
                self._connection.execute(
                    "INSERT INTO task_threads(conversation_id, mission_id, thread_json) "
                    "VALUES (?, ?, ?)",
                    (conversation_id, thread.mission_id, thread.model_dump_json()),
                )
            if thread.state in {"executing", "holding", "landing"}:
                raise LifecycleTransitionError("ACTIVE_EXECUTION_REJECTS_PREFLIGHT_REPLAN")

            parent_id = thread.current_plan_revision_id
            parent = self._revision(parent_id) if parent_id else None
            row = self._connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM plan_revisions "
                "WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            revision_number = int(row[0])
            if parent is not None and parent.status in {"proposed", "confirmed"}:
                superseded = parent.model_copy(update={"status": "superseded"})
                self._connection.execute(
                    "UPDATE plan_revisions SET record_json = ? WHERE plan_revision_id = ?",
                    (superseded.model_dump_json(), superseded.plan_revision_id),
                )

            record = PlanRevisionRecord(
                plan_revision_id=f"plan-{uuid4().hex}",
                conversation_id=conversation_id,
                mission_id=thread.mission_id,
                revision=revision_number,
                parent_plan_revision_id=parent_id,
                status="proposed",
                contract_id=contract_id,
                prepared_mission_sha256=prepared_mission_sha256,
                source_message_sha256=source_message_sha256,
                created_at=_now(),
            )
            self._connection.execute(
                "INSERT INTO plan_revisions(plan_revision_id, conversation_id, revision, "
                "record_json) VALUES (?, ?, ?, ?)",
                (
                    record.plan_revision_id,
                    conversation_id,
                    record.revision,
                    record.model_dump_json(),
                ),
            )
            updated_thread = thread.model_copy(
                update={
                    "state": "awaiting_confirmation",
                    "current_plan_revision_id": record.plan_revision_id,
                    "active_execution_id": None,
                    "updated_at": _now(),
                }
            )
            self._connection.execute(
                "UPDATE task_threads SET thread_json = ? WHERE conversation_id = ?",
                (updated_thread.model_dump_json(), conversation_id),
            )
            self._connection.commit()
            return MissionLifecycleBinding(thread=updated_thread, plan_revision=record)
        except BaseException:
            self._connection.rollback()
            raise

    def confirm_execution(
        self,
        *,
        conversation_id: str,
        plan_revision_id: str,
        contract_id: str,
        prepared_mission_sha256: str,
    ) -> tuple[TaskThread, PlanRevisionRecord, str]:
        self._begin()
        try:
            thread = self._thread(conversation_id)
            record = self._revision(plan_revision_id)
            if thread is None or record is None:
                raise LifecycleTransitionError("UNKNOWN_TASK_OR_PLAN_REVISION")
            gates = {
                "thread_awaiting_confirmation": thread.state == "awaiting_confirmation",
                "current_revision_matches": (thread.current_plan_revision_id == plan_revision_id),
                "revision_is_proposed": record.status == "proposed",
                "conversation_matches": record.conversation_id == conversation_id,
                "mission_matches": record.mission_id == thread.mission_id,
                "contract_matches": record.contract_id == contract_id,
                "prepared_hash_matches": (
                    record.prepared_mission_sha256 == prepared_mission_sha256
                ),
            }
            if not all(gates.values()):
                failed = ",".join(name for name, passed in gates.items() if not passed)
                raise LifecycleTransitionError(f"EXECUTION_CONFIRMATION_REJECTED:{failed}")
            execution_id = f"execution-{uuid4().hex}"
            executing_record = record.model_copy(update={"status": "executing"})
            executing_thread = thread.model_copy(
                update={
                    "state": "executing",
                    "active_execution_id": execution_id,
                    "updated_at": _now(),
                }
            )
            self._connection.execute(
                "UPDATE plan_revisions SET record_json = ? WHERE plan_revision_id = ?",
                (executing_record.model_dump_json(), plan_revision_id),
            )
            self._connection.execute(
                "UPDATE task_threads SET thread_json = ? WHERE conversation_id = ?",
                (executing_thread.model_dump_json(), conversation_id),
            )
            self._connection.commit()
            return executing_thread, executing_record, execution_id
        except BaseException:
            self._connection.rollback()
            raise

    def set_execution_state(
        self,
        *,
        conversation_id: str,
        execution_id: str,
        state: str,
    ) -> TaskThread:
        if state not in {"executing", "holding", "landing", "completed", "failed"}:
            raise ValueError(f"unsupported execution state: {state}")
        self._begin()
        try:
            thread = self._thread(conversation_id)
            if thread is None or thread.active_execution_id != execution_id:
                raise LifecycleTransitionError("EXECUTION_ID_NOT_ACTIVE_FOR_TASK")
            allowed = {
                "executing": {"executing", "holding", "landing", "completed", "failed"},
                "holding": {"holding", "executing", "landing", "failed"},
                "landing": {"landing", "completed", "failed"},
            }
            if thread.state not in allowed or state not in allowed[thread.state]:
                raise LifecycleTransitionError(
                    f"INVALID_EXECUTION_TRANSITION:{thread.state}->{state}"
                )
            updated = thread.model_copy(update={"state": state, "updated_at": _now()})
            if state in {"completed", "failed"}:
                revision = self._revision(thread.current_plan_revision_id or "")
                if revision is None:
                    raise LifecycleTransitionError("ACTIVE_PLAN_REVISION_MISSING")
                final_revision = revision.model_copy(update={"status": state})
                self._connection.execute(
                    "UPDATE plan_revisions SET record_json = ? WHERE plan_revision_id = ?",
                    (final_revision.model_dump_json(), final_revision.plan_revision_id),
                )
            self._connection.execute(
                "UPDATE task_threads SET thread_json = ? WHERE conversation_id = ?",
                (updated.model_dump_json(), conversation_id),
            )
            self._connection.commit()
            return updated
        except BaseException:
            self._connection.rollback()
            raise

    def binding(self, conversation_id: str) -> MissionLifecycleBinding:
        thread = self._thread(conversation_id)
        if thread is None or thread.current_plan_revision_id is None:
            raise LifecycleTransitionError("TASK_HAS_NO_PLAN_REVISION")
        revision = self._revision(thread.current_plan_revision_id)
        if revision is None:
            raise LifecycleTransitionError("TASK_PLAN_REVISION_MISSING")
        return MissionLifecycleBinding(thread=thread, plan_revision=revision)

    def import_binding(self, binding: MissionLifecycleBinding) -> MissionLifecycleBinding:
        """Import a hash-bound preparation sidecar into a fresh durable context DB."""

        self._begin()
        try:
            existing_thread = self._thread(binding.thread.conversation_id)
            existing_revision = self._revision(binding.plan_revision.plan_revision_id)
            if existing_thread is None:
                self._connection.execute(
                    "INSERT INTO task_threads(conversation_id, mission_id, thread_json) "
                    "VALUES (?, ?, ?)",
                    (
                        binding.thread.conversation_id,
                        binding.thread.mission_id,
                        binding.thread.model_dump_json(),
                    ),
                )
            elif existing_thread != binding.thread:
                raise LifecycleTransitionError("TASK_THREAD_SIDECAR_DIVERGENCE")
            if existing_revision is None:
                self._connection.execute(
                    "INSERT INTO plan_revisions(plan_revision_id, conversation_id, revision, "
                    "record_json) VALUES (?, ?, ?, ?)",
                    (
                        binding.plan_revision.plan_revision_id,
                        binding.plan_revision.conversation_id,
                        binding.plan_revision.revision,
                        binding.plan_revision.model_dump_json(),
                    ),
                )
            elif existing_revision != binding.plan_revision:
                raise LifecycleTransitionError("PLAN_REVISION_SIDECAR_DIVERGENCE")
            self._connection.commit()
            return binding
        except BaseException:
            self._connection.rollback()
            raise

    def export_debug_json(self, conversation_id: str) -> str:
        """Human-readable state without exposing the underlying mutable connection."""

        return json.dumps(
            self.binding(conversation_id).model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
