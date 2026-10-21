import { afterEach, describe, expect, it } from "vitest";

import {
  getDesktopStartupGateSession,
  resetDesktopStartupGateSession,
  setDesktopStartupGateState,
  verifyDesktopStartupGate,
} from "../desktop/startupGate";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

afterEach(() => {
  resetDesktopStartupGateSession();
});

describe("desktop startup identity gate", () => {
  it("does not let a stale account verification override a newer blocked state", async () => {
    const verification = deferred<{ status: string; user_id: string }>();
    const pending = verifyDesktopStartupGate(
      "account-a",
      () => verification.promise,
    );

    setDesktopStartupGateState("blocked", {
      accountId: "account-a",
      error: "A required update became available.",
    });
    verification.resolve({ status: "ready", user_id: "account-a" });
    await pending;

    expect(getDesktopStartupGateSession()).toMatchObject({
      status: "blocked",
      accountId: "account-a",
      error: "A required update became available.",
    });
  });

  it("binds approval to the newest signed-in account when accounts change", async () => {
    const accountA = deferred<{ status: string; user_id: string }>();
    const accountB = deferred<{ status: string; user_id: string }>();
    const pendingA = verifyDesktopStartupGate("account-a", () => accountA.promise);
    const pendingB = verifyDesktopStartupGate("account-b", () => accountB.promise);

    accountA.resolve({ status: "ready", user_id: "account-a" });
    await pendingA;
    expect(getDesktopStartupGateSession()).toMatchObject({
      status: "checking",
      accountId: "account-b",
    });

    accountB.resolve({ status: "ready", user_id: "account-b" });
    await pendingB;
    expect(getDesktopStartupGateSession()).toMatchObject({
      status: "ready",
      accountId: "account-b",
    });
  });

  it("classifies a missing session route without leaking the raw Not Found response", async () => {
    const result = await verifyDesktopStartupGate("account-a", async () => {
      throw Object.assign(new Error("Not Found"), {
        code: "NOT_FOUND",
        httpStatus: 404,
      });
    });

    expect(result).toMatchObject({
      status: "blocked",
      accountId: "account-a",
      failureCode: "runtimeSessionApiMissing",
      error: "The installed Runtime does not provide the desktop account-session API.",
    });
    expect(result.error).not.toContain("Not Found");
  });
});
