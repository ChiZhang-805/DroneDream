function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const baseMigrationUrl = new URL(
  "../../migrations/20260812500000_create_organizations.sql",
  import.meta.url,
);
const extensionMigrationUrl = new URL(
  "../../migrations/20260830010000_complete_account_cloud_contracts.sql",
  import.meta.url,
);

const migration = (
  await Promise.all([
    Deno.readTextFile(baseMigrationUrl),
    Deno.readTextFile(extensionMigrationUrl),
  ])
).join("\n");

Deno.test("organization tables are RLS protected and browser mutations are denied", () => {
  for (
    const table of [
      "organizations",
      "organization_members",
      "user_software_licenses",
      "organization_audit_log",
    ]
  ) {
    assert(
      migration.includes(
        `alter table public.${table} enable row level security`,
      ),
      `${table} must enable RLS`,
    );
    assert(
      migration.includes(
        `revoke all on table public.${table} from anon, authenticated`,
      ),
      `${table} must deny browser writes`,
    );
  }
  assert(
    migration.includes("ORGANIZATION_AUDIT_APPEND_ONLY"),
    "audit must be append-only",
  );
});

Deno.test("organization roles preserve owner hierarchy and cap delegated admins at three", () => {
  assert(
    migration.includes("role in ('owner', 'admin', 'member')"),
    "roles missing",
  );
  assert(migration.includes("if admin_count >= 3"), "admin limit missing");
  assert(
    migration.includes("ORGANIZATION_ADMIN_LIMIT"),
    "admin limit must fail closed",
  );
  assert(
    migration.includes(
      "actor := public.organization_assert_actor(p_actor_user_id, true)",
    ),
    "only owners may change delegated roles",
  );
  assert(
    migration.includes("actor.role = 'admin' and target.role <> 'member'"),
    "delegated admins must only remove regular members",
  );
});

Deno.test("removing an organization member preserves the auth user and downgrades scope", () => {
  const removal = migration.slice(
    migration.indexOf(
      "create or replace function public.organization_remove_member",
    ),
    migration.indexOf(
      "revoke all on function public.organization_remove_member",
    ),
  );
  assert(
    removal.includes("set status = 'removed'"),
    "membership row should be retained as removed state",
  );
  assert(
    !removal.includes("delete from auth.users"),
    "organization removal must never delete the auth account",
  );
  assert(
    removal.includes("plan_id = 'free'"),
    "removed member should receive Free",
  );
  assert(
    removal.includes("billing_scope = 'individual'"),
    "scope should become individual",
  );
  assert(
    removal.includes("organization_id = null"),
    "organization binding should clear",
  );
});

Deno.test("edition licenses stay explicit and compact for all five applications", () => {
  assert(
    migration.includes(
      "edition in ('universal', 'sim', 'lab', 'field', 'autonomy')",
    ),
    "all five editions must have explicit license identifiers",
  );
  assert(
    migration.includes("primary key (user_id, edition)"),
    "a user must have one authoritative state per edition",
  );
});
