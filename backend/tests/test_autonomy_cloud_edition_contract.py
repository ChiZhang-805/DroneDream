from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260820010000_enable_autonomy_assistant_edition.sql"
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
    assert (
        'export type AssistantEdition = "universal" | "sim" | "lab" | "field" | "autonomy"'
        in orchestrator
    )
    assert "(universal|sim|lab|field|autonomy)" in orchestrator
