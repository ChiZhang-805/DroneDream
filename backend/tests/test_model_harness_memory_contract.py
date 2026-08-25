from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE_MIGRATION = (
    ROOT / "supabase/migrations/20260824010000_add_model_harness_memory_namespaces.sql"
)
CONSOLIDATION_MIGRATION = (
    ROOT / "supabase/migrations/20260824020000_add_staged_consolidated_memory.sql"
)
AUTHENTICATED_MANAGEMENT_MIGRATION = (
    ROOT / "supabase/migrations/20260824030000_add_authenticated_memory_management.sql"
)
ORCHESTRATOR = ROOT / "supabase/functions/assistant-orchestrator/index.ts"
CONSOLE_PREFERENCES = ROOT / "frontend/src/features/settings/consolePreferences.ts"

NAMESPACES = (
    "account.shared",
    "optimization.control_tuning",
    "autonomy.mission",
    "asset.qualification",
    "experiment.simulation",
    "workflow.cross_edition",
    "validation.hardware",
    "calibration.system",
    "transfer.sim_to_real",
    "transfer.real_to_sim",
    "operations.field",
)


def test_memory_is_account_tenant_and_responsibility_bounded_not_edition_bounded() -> None:
    migration = NAMESPACE_MIGRATION.read_text(encoding="utf-8")
    edge = ORCHESTRATOR.read_text(encoding="utf-8")

    for namespace in NAMESPACES:
        assert f'"{namespace}"' in edge or f"'{namespace}'" in migration
    assert "responsibility_namespace" in migration
    assert "console_memory_records_account_namespace_idx" in migration
    assert "user_id, tenant_id, organization_id, responsibility_namespace" in migration
    assert "force row level security" in migration
    assert "user_id = auth.uid()" in migration
    assert "tenant_id = auth.uid()" in migration
    assert "membership.status = 'active'" in migration

    record_query = edge.split('.from("console_memory_records")', 1)[1].split(".limit(16)", 1)[0]
    assert '.eq("user_id", userId)' in record_query
    assert '.eq("tenant_id", tenantId)' in record_query
    assert '.eq("organization_id", storedOrganization)' in record_query
    assert '.in("responsibility_namespace", readableNamespaces)' in record_query
    assert '.eq("status", "active")' in record_query
    assert '.eq("edition"' not in record_query
    assert '.eq("workspace_id"' not in record_query


def test_memory_uses_session_candidates_then_consolidates_with_conflict_and_forget_support() -> (
    None
):
    migration = CONSOLIDATION_MIGRATION.read_text(encoding="utf-8")
    edge = ORCHESTRATOR.read_text(encoding="utf-8")

    assert "create table if not exists public.console_memory_candidates" in migration
    for field in (
        "source_kind",
        "evidence_count",
        "confidence",
        "first_seen",
        "last_seen",
        "status",
        "expires_at",
        "retrieval_metadata",
        "memory_kind",
    ):
        assert field in migration
    assert "group by candidate.conversation_id" in migration
    assert "p_source_kind = 'explicit_user_update' and support_confidence >= 0.900" in migration
    assert "support_count >= 2" not in migration
    assert "status = 'conflict'" in migration
    assert "status = 'superseded'" in migration
    assert "console_memory_resolve_candidate" in migration
    assert "console_memory_forget" in migration
    forget_function = migration.split("create or replace function public.console_memory_forget", 1)[
        1
    ].split("$$;", 1)[0]
    assert "status in ('staged', 'accepted', 'conflict')" in forget_function
    assert "now() + interval '30 days'" in migration
    assert "now() + interval '180 days'" in migration
    assert 'rpc("console_memory_stage_candidate"' in edge
    assert '.from("console_memory_records").insert' not in edge

    assert 'precedence: ["current_request", "session", "domain_memory", "account_defaults"]' in edge
    assert "unresolved_session_conflicts" in edge
    assert "boundedMemoryItems(consolidated ?? [], 12, 12_000)" in edge


def test_memory_rejects_secrets_instructions_and_task_scoped_authority() -> None:
    namespace_migration = NAMESPACE_MIGRATION.read_text(encoding="utf-8")
    consolidation = CONSOLIDATION_MIGRATION.read_text(encoding="utf-8")
    edge = ORCHESTRATOR.read_text(encoding="utf-8")

    for forbidden in (
        "operatorapproval",
        "actuatorauthority",
        "flightauthority",
        "parameterwriteauthority",
        "onetimeconfirmation",
    ):
        assert forbidden in namespace_migration
        assert forbidden in edge
    assert "console_memory_payload_is_safe" in consolidation
    assert "UNSAFE_MEMORY_CANDIDATE" in consolidation
    assert "UNSAFE_LONG_TERM_MEMORY" in consolidation
    assert "systemprompt" in consolidation
    assert "clientsecret" in consolidation
    assert (
        "authority[[:space:]_-]*(:|=)?[[:space:]_-]*(granted|true|enabled|active)" in consolidation
    )
    assert "isSafeLongTermMemoryValue" in edge


def test_legacy_scopes_are_migrated_without_losing_source_provenance() -> None:
    migration = NAMESPACE_MIGRATION.read_text(encoding="utf-8")

    for scope in (
        "chat_preferences",
        "experiment_defaults",
        "device_vehicle",
        "metrics_constraints",
        "safety_approvals",
        "workflow_tools",
        "reports_delivery",
        "collaboration_organization",
        "files_artifacts",
    ):
        assert f"when '{scope}'" in migration or scope in migration
    assert "payload ->> 'artifact_kind'" in migration
    assert "Source edition metadata only" in migration
    assert "Source workspace metadata only" in migration
    assert "conversation messages and summaries remain conversation-isolated" in migration


def test_authenticated_memory_management_uses_auth_uid_and_controlled_rpcs() -> None:
    migration = AUTHENTICATED_MANAGEMENT_MIGRATION.read_text(encoding="utf-8")
    frontend = CONSOLE_PREFERENCES.read_text(encoding="utf-8")

    forget_signature = migration.split(
        "create or replace function public.console_memory_forget_current_user", 1
    )[1].split("returns integer", 1)[0]
    resolve_signature = migration.split(
        "create or replace function public.console_memory_resolve_current_user", 1
    )[1].split("returns public.console_memory_candidates", 1)[0]
    assert "p_user_id" not in forget_signature
    assert "p_user_id" not in resolve_signature
    assert migration.count("caller_user_id uuid := auth.uid()") == 2
    assert "candidate.user_id = caller_user_id" in migration
    assert "memory.user_id = caller_user_id" in migration
    assert "p_tenant_id" in migration and "p_organization_id" in migration
    assert "grant execute on function public.console_memory_forget_current_user" in migration
    assert "grant execute on function public.console_memory_resolve_current_user" in migration
    assert ") to authenticated;" in migration
    assert "grant select on public.console_memory_candidates to authenticated" in migration

    assert '.rpc(\n    "console_memory_forget_current_user"' in frontend
    assert '"console_memory_resolve_current_user"' in frontend
    assert '.from("console_memory_records")\n    .delete()' not in frontend
    assert "forgetConsoleMemoryDomain" in frontend
    assert "forgetConsoleMemoryRecord" in frontend
    memory_query = frontend.split('.from("console_memory_records")', 1)[1].split(".limit(64)", 1)[0]
    assert '.in("responsibility_namespace"' in memory_query
    assert '.eq("workspace_id"' not in memory_query
    assert '.eq("edition"' not in memory_query


def test_assistant_outputs_and_persists_the_unified_model_harness_contract() -> None:
    edge = ORCHESTRATOR.read_text(encoding="utf-8")

    assert "dronedream.model-harness-control-plane-ref.v1" in edge
    assert "dronedream.model-harness-input.v1" in edge
    assert "dronedream.model-harness-output.v1" in edge
    assert "model_harness_control_plane_ref: controlPlaneRef" in edge
    assert "model_harness_control_plane_ref:" in edge
    assert "responsibility_namespace_by_task: TASK_MEMORY_NAMESPACE" in edge
    assert (
        "p_source_metadata: {\n          model_harness_control_plane_ref: controlPlaneRef" in edge
    )
