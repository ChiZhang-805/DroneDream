from dronedream_agent_core.context import ContextStore
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.lifecycle import LifecycleTransitionError


def test_same_task_keeps_mission_id_and_supersedes_only_plan_revision(tmp_path) -> None:
    context = ContextStore(tmp_path / "context.sqlite3")
    try:
        first = context.lifecycle.record_plan_revision(
            conversation_id="conversation-a",
            contract_id="mission-contract-a",
            prepared_mission_sha256=sha256_json({"prepared": 1}),
            source_message_sha256=sha256_json({"message": 1}),
        )
        second = context.lifecycle.record_plan_revision(
            conversation_id="conversation-a",
            contract_id="mission-contract-b",
            prepared_mission_sha256=sha256_json({"prepared": 2}),
            source_message_sha256=sha256_json({"message": 2}),
        )

        assert first.thread.mission_id == second.thread.mission_id
        assert first.plan_revision.plan_revision_id != second.plan_revision.plan_revision_id
        assert second.plan_revision.revision == 2
        assert second.plan_revision.parent_plan_revision_id == first.plan_revision.plan_revision_id
        assert (
            context.lifecycle.get_revision(first.plan_revision.plan_revision_id).status
            == "superseded"
        )
    finally:
        context.close()


def test_confirmed_execution_rejects_preflight_replan_and_wrong_identity(tmp_path) -> None:
    context = ContextStore(tmp_path / "context.sqlite3")
    prepared_hash = sha256_json({"prepared": 1})
    try:
        binding = context.lifecycle.record_plan_revision(
            conversation_id="conversation-a",
            contract_id="mission-contract-a",
            prepared_mission_sha256=prepared_hash,
            source_message_sha256=sha256_json({"message": 1}),
        )
        _, _, execution_id = context.lifecycle.confirm_execution(
            conversation_id="conversation-a",
            plan_revision_id=binding.plan_revision.plan_revision_id,
            contract_id="mission-contract-a",
            prepared_mission_sha256=prepared_hash,
        )

        try:
            context.lifecycle.record_plan_revision(
                conversation_id="conversation-a",
                contract_id="mission-contract-b",
                prepared_mission_sha256=sha256_json({"prepared": 2}),
                source_message_sha256=sha256_json({"message": 2}),
            )
        except LifecycleTransitionError as exc:
            assert str(exc) == "ACTIVE_EXECUTION_REJECTS_PREFLIGHT_REPLAN"
        else:
            raise AssertionError("active execution accepted a preflight replan")

        context.lifecycle.set_execution_state(
            conversation_id="conversation-a",
            execution_id=execution_id,
            state="holding",
        )
        context.lifecycle.set_execution_state(
            conversation_id="conversation-a",
            execution_id=execution_id,
            state="landing",
        )
        final = context.lifecycle.set_execution_state(
            conversation_id="conversation-a",
            execution_id=execution_id,
            state="failed",
        )
        assert final.state == "failed"
    finally:
        context.close()
