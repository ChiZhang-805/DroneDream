import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deleteCurrentAccount } from "../features/auth/accountSelfService";

const tokenStoreMock = vi.hoisted(() => ({ token: "account-token" as string | null }));

vi.mock("../features/auth/authTokenStore", () => ({
  getAuthAccessToken: () => tokenStoreMock.token,
}));

describe("account self-service client", () => {
  beforeEach(() => {
    tokenStoreMock.token = "account-token";
    vi.stubEnv("VITE_ACCOUNT_SELF_SERVICE_URL", "https://api.example.test/account-self-service");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("sends the explicit deletion confirmation with the current session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ deleted: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteCurrentAccount();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example.test/account-self-service/delete");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ confirmation: "DELETE" }),
      headers: expect.objectContaining({ Authorization: "Bearer account-token" }),
    });
  });

  it("surfaces stable server errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: "ACCOUNT_DELETE_TRANSFER_FOUNDER",
        message: "Transfer the organization Founder role before deleting this account.",
      },
    }), { status: 409, headers: { "Content-Type": "application/json" } })));

    await expect(deleteCurrentAccount()).rejects.toMatchObject({
      code: "ACCOUNT_DELETE_TRANSFER_FOUNDER",
    });
  });
});
