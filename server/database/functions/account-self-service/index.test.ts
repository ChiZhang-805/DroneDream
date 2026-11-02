import {
  AccountSelfServiceError,
  type AccountSelfServiceDependencies,
  handleAccountSelfServiceRequest,
} from "./index.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const USER_ID = "11111111-1111-4111-8111-111111111111";

function dependencies(
  overrides: Partial<AccountSelfServiceDependencies> = {},
): AccountSelfServiceDependencies {
  return {
    authenticate: () => Promise.resolve({ id: USER_ID }),
    deleteAccount: () => Promise.resolve(),
    ...overrides,
  };
}

function request(body: unknown = { confirmation: "DELETE" }, token = "test-token"): Request {
  return new Request("https://example.test/account-self-service/delete", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

Deno.test("account self-service authenticates before deleting the same account", async () => {
  let deletedUserId = "";
  const response = await handleAccountSelfServiceRequest(request(), dependencies({
    deleteAccount(userId) {
      deletedUserId = userId;
      return Promise.resolve();
    },
  }));
  const body = await response.json();
  assert(response.status === 200, "expected a successful deletion response");
  assert(body.deleted === true, "expected deleted=true");
  assert(deletedUserId === USER_ID, "expected deletion to target the authenticated account");
});

Deno.test("account self-service requires the exact permanent deletion confirmation", async () => {
  const response = await handleAccountSelfServiceRequest(
    request({ confirmation: "delete" }),
    dependencies(),
  );
  const body = await response.json();
  assert(response.status === 400, "expected invalid confirmation to be rejected");
  assert(body.error.code === "ACCOUNT_DELETE_CONFIRMATION_REQUIRED", "expected a stable error code");
});

Deno.test("account self-service returns safe founder transfer errors", async () => {
  const response = await handleAccountSelfServiceRequest(request(), dependencies({
    deleteAccount() {
      return Promise.reject(new AccountSelfServiceError(
        "ACCOUNT_DELETE_TRANSFER_FOUNDER",
        "Transfer the organization Founder role before deleting this account.",
        409,
      ));
    },
  }));
  const body = await response.json();
  assert(response.status === 409, "expected founder deletion to be blocked");
  assert(body.error.code === "ACCOUNT_DELETE_TRANSFER_FOUNDER", "expected founder transfer code");
});

Deno.test("account self-service rejects missing authorization", async () => {
  const noToken = new Request("https://example.test/account-self-service/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: "DELETE" }),
  });
  const response = await handleAccountSelfServiceRequest(noToken, dependencies());
  assert(response.status === 401, "expected authentication to be required");
});
