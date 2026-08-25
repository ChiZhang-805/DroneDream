const migrationUrl = new URL(
  "../migrations/20260824060000_add_authenticated_memory_projection.sql",
  import.meta.url,
);
const migration = (await Deno.readTextFile(migrationUrl)).toLowerCase();

function assertIncludes(haystack: string, needle: string, message: string): void {
  if (!haystack.includes(needle.toLowerCase())) throw new Error(message);
}

function functionBody(name: string): string {
  const marker = `create or replace function public.${name}`;
  const start = migration.indexOf(marker);
  if (start < 0) throw new Error(`missing ${name}`);
  const end = migration.indexOf("$$;", start);
  if (end < 0) throw new Error(`unterminated ${name}`);
  return migration.slice(start, end);
}

Deno.test("desktop projection derives its owner from auth.uid", () => {
  const body = functionBody("console_memory_stage_current_user");
  assertIncludes(body, "caller_user_id uuid := auth.uid()", "owner must come from JWT");
  assertIncludes(body, "console_memory_boundary_allowed", "tenant boundary must be checked");
  if (body.includes("p_user_id")) throw new Error("public projection RPC must not accept user id");
});

Deno.test("desktop projection cannot self-promote cloud memory", () => {
  const body = functionBody("console_memory_stage_current_user");
  assertIncludes(
    body,
    "'validated_plan_candidate'",
    "desktop writes must remain non-promotable candidates",
  );
  if (body.includes("'explicit_user_update'")) {
    throw new Error("desktop projection RPC must not claim direct-user promotion");
  }
  assertIncludes(
    migration,
    "grant execute on function public.console_memory_stage_current_user",
    "authenticated callers need the narrow RPC",
  );
  if (migration.includes("to anon")) throw new Error("anonymous callers must not stage memory");
});

Deno.test("cloud projection revisions are monotonic", () => {
  assertIncludes(migration, "projection_revision bigint not null default 1", "revision missing");
  const body = functionBody("console_memory_increment_projection_revision");
  assertIncludes(
    body,
    "new.projection_revision := old.projection_revision + 1",
    "revision must advance on every record update",
  );
});
