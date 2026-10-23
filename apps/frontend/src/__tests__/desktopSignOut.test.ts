import { afterEach, describe, expect, it, vi } from "vitest";

import {
  approveDesktopStartupGateForAccount,
  getDesktopStartupGateSession,
} from "../desktop/startupGate";
import { restartDesktopLauncherAfterSignOut } from "../desktop/signOut";

describe("desktop sign-out lifecycle", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("returns a desktop edition to a clean launcher document", () => {
    const reload = vi.fn();
    approveDesktopStartupGateForAccount("pilot-1");
    window.history.replaceState(
      null,
      "",
      "/#/autonomy/conversations/task-1?panel=account",
    );

    expect(restartDesktopLauncherAfterSignOut({
      isDesktop: () => true,
      reload,
    })).toBe(true);

    expect(window.location.hash).toBe("#/desktop/setup");
    expect(window.location.search).toBe("");
    expect(getDesktopStartupGateSession()).toMatchObject({
      status: "idle",
      accountId: null,
      checkedAt: null,
    });
    expect(reload).toHaveBeenCalledOnce();
  });

  it("does not redirect the hosted web app", () => {
    const reload = vi.fn();
    window.history.replaceState(null, "", "/assistant");

    expect(restartDesktopLauncherAfterSignOut({
      isDesktop: () => false,
      reload,
    })).toBe(false);

    expect(window.location.pathname).toBe("/assistant");
    expect(reload).not.toHaveBeenCalled();
  });
});
