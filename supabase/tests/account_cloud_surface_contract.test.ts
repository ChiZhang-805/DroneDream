import { assert, assertStringIncludes } from "jsr:@std/assert@1";

const repoRoot = new URL("../../", import.meta.url);

Deno.test("model usage returns the authoritative account billing boundary", async () => {
  const gateway = await Deno.readTextFile(
    new URL("supabase/functions/model-gateway/index.ts", repoRoot),
  );
  const migration = await Deno.readTextFile(
    new URL(
      "supabase/migrations/20260830020000_harden_account_cloud_surface.sql",
      repoRoot,
    ),
  );

  assertStringIncludes(gateway, '.rpc("model_access_account_snapshot"');
  assertStringIncludes(gateway, "account: accountResult.data");
  assertStringIncludes(
    migration,
    "function public.model_access_account_snapshot",
  );
  for (
    const field of [
      "billing_scope",
      "organization_id",
      "organization_name",
      "organization_role",
    ]
  ) {
    assertStringIncludes(migration, `'${field}'`);
  }
});

Deno.test("database RPC exposure is closed and client RPCs are allow-listed", async () => {
  const migration = await Deno.readTextFile(
    new URL(
      "supabase/migrations/20260830020000_harden_account_cloud_surface.sql",
      repoRoot,
    ),
  );

  assertStringIncludes(
    migration,
    "revoke execute on all functions in schema public from public, anon, authenticated",
  );
  assertStringIncludes(
    migration,
    "grant execute on all functions in schema public to service_role",
  );
  for (
    const clientRoutine of [
      "community_list_topics",
      "community_list_topics_v2",
      "community_list_comments",
      "community_count_topics",
      "community_media_upload_allowed",
      "console_memory_forget_current_user",
      "console_memory_resolve_current_user",
      "console_memory_permanently_delete_current_user",
      "console_memory_permanently_delete_all_current_user",
      "console_memory_release_deletion_tombstone_current_user",
      "console_memory_stage_current_user",
    ]
  ) {
    assert(
      migration.includes(`function public.${clientRoutine}`),
      `${clientRoutine} is missing from the explicit client allow-list`,
    );
  }
});
