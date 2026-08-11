function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const migrationUrl = new URL(
  "../../migrations/20260812010000_create_organization_management.sql",
  import.meta.url,
);

const migration = await Deno.readTextFile(migrationUrl);

Deno.test("organization tables are RLS protected and browser mutations are denied", () => {
  for (const table of [
    "organizations",
    "organization_members",
    "user_software_licenses",
    "organization_audit_log",
  ]) {
    assert(
      migration.includes(`alter table public.${table} enable row level security`),
      `${table} must enable RLS`,
    );
    assert(
      migration.includes(`revoke all on table public.${table} from anon, authenticated`),
      `${table} must deny browser writes`,
    );
  }
  assert(migration.includes("ORGANIZATION_AUDIT_APPEND_ONLY"), "audit must be append-only");
});

Deno.test("organization roles preserve owner hierarchy and cap delegated admins at three", () => {
  assert(migration.includes("role in ('owner', 'admin', 'member')"), "roles missing");
  assert(migration.includes("if admin_count >= 3"), "admin limit missing");
  assert(migration.includes("ORGANIZATION_ADMIN_LIMIT"), "admin limit must fail closed");
  assert(
    migration.includes("actor := public.organization_assert_actor(p_actor_user_id, true)"),
    "only owners may change delegated roles",
  );
  assert(
    migration.includes("actor.role = 'admin' and target.role <> 'member'"),
    "delegated admins must only remove regular members",
  );
});

Deno.test("removing an organization member preserves the auth user and downgrades scope", () => {
  assert(
    migration.includes("delete from public.organization_members"),
    "membership row should be removed",
  );
  assert(
    !migration.includes("delete from auth.users"),
    "organization removal must never delete the auth account",
  );
  assert(migration.includes("plan_id = 'free'"), "removed member should receive Free");
  assert(migration.includes("billing_scope = 'individual'"), "scope should become individual");
  assert(migration.includes("organization_id = null"), "organization binding should clear");
});

Deno.test("edition licenses stay explicit and compact for all four applications", () => {
  assert(
    migration.includes("edition in ('universal', 'sim', 'lab', 'field')"),
    "all four editions must have explicit license identifiers",
  );
  assert(
    migration.includes("primary key (user_id, edition)"),
    "a user must have one authoritative state per edition",
  );
});
