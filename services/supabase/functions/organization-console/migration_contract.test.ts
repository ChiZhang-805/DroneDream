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
const hierarchyMigrationUrl = new URL(
  "../../migrations/20261020020000_complete_organization_role_hierarchy.sql",
  import.meta.url,
);
const passwordMigrationUrl = new URL(
  "../../migrations/20261020030000_secure_organization_join_password.sql",
  import.meta.url,
);
const recoverablePasswordMigrationUrl = new URL(
  "../../migrations/20261020031000_encrypt_recoverable_organization_join_secret.sql",
  import.meta.url,
);

const migration = (
  await Promise.all([
    Deno.readTextFile(baseMigrationUrl),
    Deno.readTextFile(extensionMigrationUrl),
    Deno.readTextFile(hierarchyMigrationUrl),
    Deno.readTextFile(passwordMigrationUrl),
    Deno.readTextFile(recoverablePasswordMigrationUrl),
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

Deno.test("Founder transfer is restricted to administrators and is atomic", () => {
  const transfer = migration.slice(
    migration.indexOf("create or replace function public.organization_transfer_founder"),
    migration.indexOf("revoke all on function public.organization_transfer_founder"),
  );
  assert(transfer.includes("target.role <> 'admin'"), "Founder must transfer only to an admin");
  assert(transfer.includes("set role = 'owner'"), "target must become Founder");
  assert(transfer.includes("set role = 'admin'"), "previous Founder must become admin");
  assert(transfer.includes("set owner_user_id = target.user_id"), "organization owner must move atomically");
});

Deno.test("Business plan ceilings and downgrade clamping are database enforced", () => {
  assert(migration.includes("ORGANIZATION_MEMBER_PLAN_EXCEEDS_FOUNDER"), "member plan ceiling missing");
  assert(migration.includes("when 'pro' then p_plan_id in ('free', 'plus', 'pro')"), "Pro matrix missing");
  assert(migration.includes("when 'plus' then p_plan_id in ('free', 'plus')"), "Plus matrix missing");
  assert(migration.includes("else p_plan_id = 'free'"), "Free matrix missing");
  assert(migration.includes("A Founder upgrade never changes members"), "upgrade preservation missing");
});

Deno.test("department structures enforce one or two scoped managers", () => {
  assert(migration.includes("structure_model in ('flat', 'department_single', 'department_dual')"), "structure models missing");
  assert(migration.includes("structure = 'department_single' then 1 else 2"), "department manager limits missing");
  assert(migration.includes("ORGANIZATION_DEPARTMENT_PERMISSION_REQUIRED"), "department-scoped plan management missing");
});

Deno.test("organization passwords are one-way hashed and required for joins", () => {
  assert(migration.includes("join_password_hash text"), "password hash column missing");
  assert(migration.includes("extensions.gen_salt('bf', 12)"), "password must use a slow salted hash");
  assert(migration.includes("extensions.crypt(p_password, organization.join_password_hash)"), "join password verification missing");
  assert(migration.includes("drop function if exists public.organization_request_join(uuid, text, text)"), "passwordless join entry point must be removed");
  assert(!migration.includes("join_password text"), "plaintext organization passwords must never be stored");
  assert(migration.includes("join_password_ciphertext text"), "recoverable password must be encrypted at rest");
});
