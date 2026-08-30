import {
  handleOrganizationConsoleRequest,
  type OrganizationConsoleDependencies,
  OrganizationConsoleError,
  type OrganizationSnapshot,
} from "./index.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const ACTOR_ID = "11111111-1111-4111-8111-111111111111";
const TARGET_ID = "22222222-2222-4222-8222-222222222222";

function snapshot(): OrganizationSnapshot {
  return {
    organization: {
      id: "33333333-3333-4333-8333-333333333333",
      name: "Aerial Systems Lab",
      plan: "pro",
      status: "active",
      owner_user_id: ACTOR_ID,
    },
    actor: {
      user_id: ACTOR_ID,
      role: "owner",
      can_manage_members: true,
      can_manage_admins: true,
    },
    admin_limit: 3,
    members: [{
      id: ACTOR_ID,
      display_name: "Owner",
      email: "owner@example.test",
      role: "owner",
      plan: "pro",
      subscription_status: "active",
      created_at: "2026-08-01T00:00:00.000Z",
      last_sign_in_at: "2026-08-12T00:00:00.000Z",
      licenses: ["universal", "lab"],
    }],
  };
}

function dependencies(
  overrides: Partial<OrganizationConsoleDependencies> = {},
): OrganizationConsoleDependencies {
  return {
    authenticate: () => Promise.resolve({ id: ACTOR_ID }),
    access: () =>
      Promise.resolve({
        authorized: true,
        organization_id: "33333333-3333-4333-8333-333333333333",
        role: "owner",
      }),
    snapshot: () => Promise.resolve(snapshot()),
    findUserIdByEmail: () => Promise.resolve(TARGET_ID),
    addMember: () => Promise.resolve(),
    setMemberRole: () => Promise.resolve(),
    removeMember: () => Promise.resolve(),
    ...overrides,
  };
}

function request(
  route = "",
  method = "GET",
  body?: unknown,
  token = "test-token",
): Request {
  return new Request(
    `https://getdronedream.com/functions/v1/organization-console${route}`,
    {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    },
  );
}

Deno.test("organization access requires a verified account", async () => {
  const req = request("/access");
  req.headers.delete("Authorization");
  const response = await handleOrganizationConsoleRequest(req, dependencies());
  assert(response.status === 401, "missing bearer token must fail");
});

Deno.test("organization access can hide management from a regular member", async () => {
  const response = await handleOrganizationConsoleRequest(
    request("/access"),
    dependencies({
      access: () =>
        Promise.resolve({
          authorized: false,
          organization_id: "33333333-3333-4333-8333-333333333333",
          role: "member",
        }),
    }),
  );
  const body = await response.json();
  assert(response.status === 200, "access lookup should be safe for a member");
  assert(
    body.data.authorized === false,
    "member must not see management access",
  );
});

Deno.test("organization snapshot is compact and includes the four-edition portfolio", async () => {
  const response = await handleOrganizationConsoleRequest(
    request(),
    dependencies(),
  );
  const body = await response.json();
  assert(response.status === 200, "owner should read the organization");
  assert(body.data.admin_limit === 3, "delegated admin limit must be explicit");
  assert(
    body.data.members[0].licenses.join(",") === "universal,lab",
    "edition licenses must remain compact",
  );
});

Deno.test("owner can add an existing account with an exact bounded request", async () => {
  let lookup = "";
  let mutation = "";
  const response = await handleOrganizationConsoleRequest(
    request("/members", "POST", { email: "pilot@example.test", role: "admin" }),
    dependencies({
      findUserIdByEmail: (email) => {
        lookup = email;
        return Promise.resolve(TARGET_ID);
      },
      addMember: (actor, target, role) => {
        mutation = `${actor}:${target}:${role}`;
        return Promise.resolve();
      },
    }),
  );
  assert(response.status === 201, "member creation should return created");
  assert(
    lookup === "pilot@example.test",
    "email must be normalized by the route",
  );
  assert(
    mutation === `${ACTOR_ID}:${TARGET_ID}:admin`,
    "server-derived actor and resolved target must reach the RPC",
  );
});

Deno.test("member role changes and removals pass only the server-derived actor", async () => {
  const actions: string[] = [];
  const deps = dependencies({
    setMemberRole: (actor, target, role) => {
      actions.push(`role:${actor}:${target}:${role}`);
      return Promise.resolve();
    },
    removeMember: (actor, target) => {
      actions.push(`remove:${actor}:${target}`);
      return Promise.resolve();
    },
  });
  const roleResponse = await handleOrganizationConsoleRequest(
    request(`/members/${TARGET_ID}`, "PATCH", { role: "member" }),
    deps,
  );
  const removeResponse = await handleOrganizationConsoleRequest(
    request(`/members/${TARGET_ID}`, "DELETE"),
    deps,
  );
  assert(
    roleResponse.status === 200 && removeResponse.status === 200,
    "mutations should pass",
  );
  assert(
    actions[0] === `role:${ACTOR_ID}:${TARGET_ID}:member`,
    "role actor mismatch",
  );
  assert(
    actions[1] === `remove:${ACTOR_ID}:${TARGET_ID}`,
    "remove actor mismatch",
  );
});

Deno.test("organization mutations reject unknown fields, owner role, and invalid ids", async () => {
  const cases = [
    request("/members", "POST", {
      email: "pilot@example.test",
      role: "member",
      owner: true,
    }),
    request("/members", "POST", { email: "pilot@example.test", role: "owner" }),
    request("/members/not-a-uuid", "PATCH", { role: "member" }),
  ];
  for (const req of cases) {
    const response = await handleOrganizationConsoleRequest(
      req,
      dependencies(),
    );
    assert(
      response.status >= 400,
      "invalid organization mutation must fail closed",
    );
  }
});

Deno.test("administrator-limit conflicts are safe and do not leak database errors", async () => {
  const response = await handleOrganizationConsoleRequest(
    request(`/members/${TARGET_ID}`, "PATCH", { role: "admin" }),
    dependencies({
      setMemberRole: () =>
        Promise.reject(
          new OrganizationConsoleError(
            "ORGANIZATION_ADMIN_LIMIT",
            "An organization can delegate at most three administrators.",
            409,
          ),
        ),
    }),
  );
  const text = await response.text();
  assert(response.status === 409, "admin limit should remain a conflict");
  assert(
    !text.includes("postgres") && !text.includes("service_role"),
    "error leaked internals",
  );
});

Deno.test("unexpected organization failures are sanitized", async () => {
  const response = await handleOrganizationConsoleRequest(
    request(),
    dependencies({
      snapshot: () => Promise.reject(new Error("database raw secret")),
    }),
  );
  const text = await response.text();
  assert(response.status === 500, "unexpected failures must fail closed");
  assert(
    !text.includes("database raw secret"),
    "raw error must not be returned",
  );
});
