const migrationUrl = new URL(
  "../migrations/20260824050000_enforce_memory_deletion_tombstones.sql",
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

Deno.test("permanent-delete tombstones fail closed at the database write gate", () => {
  const gate = functionBody("console_memory_require_write_consent");
  assertIncludes(gate, "pg_advisory_xact_lock", "write gate must share deletion locks");
  assertIncludes(gate, "tombstone.released_at is null", "only active tombstones block");
  assertIncludes(
    gate,
    "tombstone.responsibility_namespace = 'account.all'",
    "account-wide deletion must block every namespace",
  );
  assertIncludes(
    gate,
    "tombstone.scope is null or tombstone.scope = new.scope",
    "namespace and scope tombstones must cover child writes",
  );
  assertIncludes(
    gate,
    "tombstone.memory_key_sha256 = memory_key_hash",
    "field tombstones must compare a payload-free key digest",
  );
  assertIncludes(gate, "message = 'memory_scope_tombstoned'", "blocked writes need a stable error");
});

Deno.test("tombstone release requires reconsent plus explicit confirmation", () => {
  const release = functionBody(
    "console_memory_release_deletion_tombstone_current_user",
  );
  assertIncludes(
    release,
    "p_confirm_relearn is distinct from true",
    "release must require an affirmative relearn confirmation",
  );
  assertIncludes(release, "consent.memory_enabled", "memory must be re-enabled first");
  assertIncludes(
    release,
    "p_responsibility_namespace = any(consent.write_namespaces)",
    "the target namespace must be writable",
  );
  assertIncludes(
    release,
    "consent.memory_scopes @> jsonb_build_object(p_scope, true)",
    "the exact scope must be reconsented",
  );
  assertIncludes(
    release,
    "message = 'memory_reconsent_required'",
    "missing consent must fail closed",
  );
});

Deno.test("relearn preserves deletion history and exposes no direct tombstone mutation", () => {
  const release = functionBody(
    "console_memory_release_deletion_tombstone_current_user",
  );
  assertIncludes(
    release,
    "update public.console_memory_deletion_tombstones",
    "release should annotate the audit row",
  );
  assertIncludes(
    release,
    "release_reason = 'explicit_reconsent'",
    "release reason must be explicit",
  );
  if (release.includes("delete from public.console_memory_deletion_tombstones")) {
    throw new Error("release must not erase the deletion audit row");
  }
  assertIncludes(
    migration,
    "grant execute on function public.console_memory_release_deletion_tombstone_current_user",
    "authenticated callers need only the controlled RPC",
  );
  if (
    migration.includes(
      "grant update on public.console_memory_deletion_tombstones to authenticated",
    )
  ) {
    throw new Error("authenticated callers must not update tombstones directly");
  }
});
