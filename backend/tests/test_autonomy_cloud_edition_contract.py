from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260820010000_enable_autonomy_assistant_edition.sql"
VEHICLE_MIGRATION = (
    ROOT / "supabase/migrations/20260820020000_enable_autonomy_vehicle_model_revisions.sql"
)
ASSET_MIGRATION = (
    ROOT
    / "supabase/migrations/20260822020000_replace_modeling_with_external_asset_qualification.sql"
)
ORCHESTRATOR = ROOT / "supabase/functions/assistant-orchestrator/index.ts"


def test_autonomy_cloud_edition_is_bound_across_storage_rpc_and_routes() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")

    for table in (
        "assistant_conversations",
        "assistant_runs",
        "assistant_messages",
        "assistant_artifacts",
        "assistant_run_steps",
        "assistant_files",
        "assistant_artifact_versions",
        "console_preferences",
        "console_memory_records",
    ):
        assert f"alter table public.{table}" in migration
    assert migration.count("'autonomy'") >= 10
    assert "p_edition not in ('universal', 'sim', 'lab', 'field', 'autonomy')" in migration
    assert "create or replace function public.assistant_complete_run" in migration
    assert "selected_run.edition = 'autonomy'" in migration
    asset_migration = ASSET_MIGRATION.read_text(encoding="utf-8")
    assert "'external_asset_qualification_plan'" in asset_migration
    assert "p_artifact_kind = 'external_asset_qualification_plan'" in asset_migration
    assert "create or replace function public.assistant_complete_run" in asset_migration
    assert "ASSISTANT_ARTIFACT_EDITION_MISMATCH" in migration
    assert (
        'export type AssistantEdition = "universal" | "sim" | "lab" | "field" | "autonomy"'
        in orchestrator
    )
    assert "(universal|sim|lab|field|autonomy)" in orchestrator


def test_legacy_vehicle_models_keep_a_distinct_cloud_workspace_boundary() -> None:
    migration = VEHICLE_MIGRATION.read_text(encoding="utf-8")

    assert "vehicle_model_revisions_workspace_edition_check" in migration
    assert "edition = 'universal' and workspace_id = 'console-universal'" in migration
    assert "edition = 'autonomy' and workspace_id = 'console-autonomy'" in migration
